# Copyright 2018 Google. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""SSD (via ResNet50) model definition.

Defines the SSD model and loss functions from this paper:

https://arxiv.org/pdf/1708.02002

Uses the ResNet model as a basis.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import re
import tensorflow as tf

import ssd_constants

_NMS_TILE_SIZE = 256


def _bbox_overlap(boxes, gt_boxes):
  """Calculates the overlap between proposal and ground truth boxes.

  Some `gt_boxes` may have been padded.  The returned `iou` tensor for these
  boxes will be -1.

  Args:
    boxes: a tensor with a shape of [batch_size, N, 4]. N is the number of
      proposals before groundtruth assignment (e.g., rpn_post_nms_topn). The
      last dimension is the pixel coordinates in [ymin, xmin, ymax, xmax] form.
    gt_boxes: a tensor with a shape of [batch_size, MAX_NUM_INSTANCES, 4]. This
      tensor might have paddings with a negative value.

  Returns:
    iou: a tensor with as a shape of [batch_size, N, MAX_NUM_INSTANCES].
  """
  with tf.name_scope('bbox_overlap'):
    bb_y_min, bb_x_min, bb_y_max, bb_x_max = tf.split(
        value=boxes, num_or_size_splits=4, axis=2)
    gt_y_min, gt_x_min, gt_y_max, gt_x_max = tf.split(
        value=gt_boxes, num_or_size_splits=4, axis=2)

    # Calculates the intersection area.
    i_xmin = tf.maximum(bb_x_min, tf.transpose(gt_x_min, [0, 2, 1]))
    i_xmax = tf.minimum(bb_x_max, tf.transpose(gt_x_max, [0, 2, 1]))
    i_ymin = tf.maximum(bb_y_min, tf.transpose(gt_y_min, [0, 2, 1]))
    i_ymax = tf.minimum(bb_y_max, tf.transpose(gt_y_max, [0, 2, 1]))
    i_area = tf.maximum((i_xmax - i_xmin), 0) * tf.maximum((i_ymax - i_ymin), 0)

    # Calculates the union area.
    bb_area = (bb_y_max - bb_y_min) * (bb_x_max - bb_x_min)
    gt_area = (gt_y_max - gt_y_min) * (gt_x_max - gt_x_min)
    # Adds a small epsilon to avoid divide-by-zero.
    u_area = bb_area + tf.transpose(gt_area, [0, 2, 1]) - i_area + 1e-8

    # Calculates IoU.
    iou = i_area / u_area

    return iou


def _self_suppression(iou, _, iou_sum):
  """Self suppression."""
  with tf.name_scope('self_suppresion'):
    batch_size = tf.shape(iou)[0]
    can_suppress_others = tf.cast(
        tf.reshape(tf.reduce_max(iou, 1) <= 0.5, [batch_size, -1, 1]),
        iou.dtype)
    iou_suppressed = tf.reshape(
        tf.cast(tf.reduce_max(can_suppress_others * iou, 1) <= 0.5, iou.dtype),
        [batch_size, -1, 1]) * iou
    iou_sum_new = tf.reduce_sum(iou_suppressed, [1, 2])
    return [
        iou_suppressed,
        tf.reduce_any(iou_sum - iou_sum_new > 0.5), iou_sum_new
    ]


def _cross_suppression(boxes, box_slice, iou_threshold, inner_idx):
  with tf.name_scope('cross_suppresion'):
    batch_size = tf.shape(boxes)[0]
    new_slice = tf.slice(boxes, [0, inner_idx * _NMS_TILE_SIZE, 0],
                         [batch_size, _NMS_TILE_SIZE, 4])
    iou = _bbox_overlap(new_slice, box_slice)
    ret_slice = tf.expand_dims(
        tf.cast(tf.reduce_all(iou < iou_threshold, [1]), box_slice.dtype),
        2) * box_slice
    return boxes, ret_slice, iou_threshold, inner_idx + 1


def _suppression_loop_body(boxes, iou_threshold, output_size, idx):
  """Process boxes in the range [idx*_NMS_TILE_SIZE, (idx+1)*_NMS_TILE_SIZE).

  Args:
    boxes: a tensor with a shape of [batch_size, anchors, 4].
    iou_threshold: a float representing the threshold for deciding whether boxes
      overlap too much with respect to IOU.
    output_size: an int32 tensor of size [batch_size]. Representing the number
      of selected boxes for each batch.
    idx: an integer scalar representing induction variable.

  Returns:
    boxes: updated boxes.
    iou_threshold: pass down iou_threshold to the next iteration.
    output_size: the updated output_size.
    idx: the updated induction variable.
  """
  with tf.name_scope('suppresion_loop_body'):
    num_tiles = tf.shape(boxes)[1] // _NMS_TILE_SIZE
    batch_size = tf.shape(boxes)[0]

    # Iterates over tiles that can possibly suppress the current tile.
    box_slice = tf.slice(boxes, [0, idx * _NMS_TILE_SIZE, 0],
                         [batch_size, _NMS_TILE_SIZE, 4])
    _, box_slice, _, _ = tf.while_loop(
        lambda _boxes, _box_slice, _threshold, inner_idx: inner_idx < idx,
        _cross_suppression, [boxes, box_slice, iou_threshold,
                             tf.constant(0)])

    # Iterates over the current tile to compute self-suppression.
    iou = _bbox_overlap(box_slice, box_slice)
    mask = tf.expand_dims(
        tf.reshape(tf.range(_NMS_TILE_SIZE), [1, -1]) > tf.reshape(
            tf.range(_NMS_TILE_SIZE), [-1, 1]), 0)
    iou *= tf.cast(tf.logical_and(mask, iou >= iou_threshold), iou.dtype)
    suppressed_iou, _, _ = tf.while_loop(
        lambda _iou, loop_condition, _iou_sum: loop_condition,
        _self_suppression,
        [iou, tf.constant(True),
         tf.reduce_sum(iou, [1, 2])])
    suppressed_box = tf.reduce_sum(suppressed_iou, 1) > 0
    box_slice *= tf.expand_dims(1.0 - tf.cast(suppressed_box, box_slice.dtype),
                                2)

    # Uses box_slice to update the input boxes.
    mask = tf.reshape(
        tf.cast(tf.equal(tf.range(num_tiles), idx), boxes.dtype), [1, -1, 1, 1])
    boxes = tf.tile(tf.expand_dims(
        box_slice, [1]), [1, num_tiles, 1, 1]) * mask + tf.reshape(
            boxes, [batch_size, num_tiles, _NMS_TILE_SIZE, 4]) * (1 - mask)
    boxes = tf.reshape(boxes, [batch_size, -1, 4])

    # Updates output_size.
    output_size += tf.reduce_sum(
        tf.cast(tf.reduce_any(box_slice > 0, [2]), tf.int32), [1])
    return boxes, iou_threshold, output_size, idx + 1


def non_max_suppression_padded(scores, boxes, max_output_size, iou_threshold):
  """A wrapper that handles non-maximum suppression.

  Assumption:
    * The boxes are sorted by scores unless the box is a dot (all coordinates
      are zero).
    * Boxes with higher scores can be used to suppress boxes with lower scores.

  The overal design of the algorithm is to handle boxes tile-by-tile:

  boxes = boxes.pad_to_multiply_of(tile_size)
  num_tiles = len(boxes) // tile_size
  output_boxes = []
  for i in range(num_tiles):
    box_tile = boxes[i*tile_size : (i+1)*tile_size]
    for j in range(i - 1):
      suppressing_tile = boxes[j*tile_size : (j+1)*tile_size]
      iou = _bbox_overlap(box_tile, suppressing_tile)
      # if the box is suppressed in iou, clear it to a dot
      box_tile *= _update_boxes(iou)
    # Iteratively handle the diagnal tile.
    iou = _box_overlap(box_tile, box_tile)
    iou_changed = True
    while iou_changed:
      # boxes that are not suppressed by anything else
      suppressing_boxes = _get_suppressing_boxes(iou)
      # boxes that are suppressed by suppressing_boxes
      suppressed_boxes = _get_suppressed_boxes(iou, suppressing_boxes)
      # clear iou to 0 for boxes that are suppressed, as they cannot be used
      # to suppress other boxes any more
      new_iou = _clear_iou(iou, suppressed_boxes)
      iou_changed = (new_iou != iou)
      iou = new_iou
    # remaining boxes that can still suppress others, are selected boxes.
    output_boxes.append(_get_suppressing_boxes(iou))
    if len(output_boxes) >= max_output_size:
      break

  Args:
    scores: a tensor with a shape of [batch_size, anchors].
    boxes: a tensor with a shape of [batch_size, anchors, 4].
    max_output_size: a scalar integer `Tensor` representing the maximum number
      of boxes to be selected by non max suppression.
    iou_threshold: a float representing the threshold for deciding whether boxes
      overlap too much with respect to IOU.

  Returns:
    nms_scores: a tensor with a shape of [batch_size, anchors]. It has same
      dtype as input scores.
    nms_proposals: a tensor with a shape of [batch_size, anchors, 4]. It has
      same dtype as input boxes.
  """
  # TODO(wangtao): Filter out score <= ssd_constants.MIN_SCORE.
  with tf.name_scope('nms'):
    batch_size = tf.shape(boxes)[0]
    num_boxes = tf.shape(boxes)[1]
    pad = tf.cast(
        tf.ceil(tf.cast(num_boxes, tf.float32) / _NMS_TILE_SIZE),
        tf.int32) * _NMS_TILE_SIZE - num_boxes
    boxes = tf.pad(tf.cast(boxes, tf.float32), [[0, 0], [0, pad], [0, 0]])
    scores = tf.pad(tf.cast(scores, tf.float32), [[0, 0], [0, pad]])
    num_boxes += pad

    def _loop_cond(unused_boxes, unused_threshold, output_size, idx):
      return tf.logical_and(
          tf.reduce_min(output_size) < max_output_size,
          idx < num_boxes // _NMS_TILE_SIZE)

    selected_boxes, _, output_size, _ = tf.while_loop(
        _loop_cond, _suppression_loop_body, [
            boxes, iou_threshold,
            tf.zeros([batch_size], tf.int32),
            tf.constant(0)
        ])
    idx = num_boxes - tf.cast(
        tf.nn.top_k(
            tf.cast(tf.reduce_any(selected_boxes > 0, [2]), tf.int32) *
            tf.expand_dims(tf.range(num_boxes, 0, -1), 0), max_output_size)[0],
        tf.int32)
    batch_idx = tf.minimum(idx, num_boxes - 1)
    one_hot_idx = tf.one_hot(batch_idx, num_boxes)
    boxes = tf.einsum('xzw,xyz->xyw', boxes, one_hot_idx)
    boxes = boxes * tf.cast(
        tf.reshape(tf.range(max_output_size), [1, -1, 1]) < tf.reshape(
            output_size, [-1, 1, 1]), boxes.dtype)
    scores = tf.einsum('xyz,xz->xy', one_hot_idx, scores)
    scores = scores * tf.cast(
        tf.reshape(tf.range(max_output_size), [1, -1]) < tf.reshape(
            output_size, [-1, 1]), scores.dtype)
    return scores, boxes


def batch_norm_relu(inputs,
                    is_training_bn,
                    relu=True,
                    init_zero=False,
                    use_fused_bn=False,
                    data_format='channels_last',
                    name=None):
  """Performs a batch normalization followed by a ReLU.

  Args:
    inputs: `Tensor` of shape `[batch, channels, ...]`.
    is_training_bn: `bool` for whether the model is training.
    relu: `bool` if False, omits the ReLU operation.
    init_zero: `bool` if True, initializes scale parameter of batch
        normalization with 0 instead of 1 (default).
    use_fused_bn: 'bool' whether use fused batch norm variables.
    data_format: `str` either "channels_first" for `[batch, channels, height,
        width]` or "channels_last for `[batch, height, width, channels]`.
    name: the name of the batch normalization layer

  Returns:
    A normalized `Tensor` with the same `data_format`.
  """
  if not is_training_bn and use_fused_bn:
    return tf.nn.relu(inputs) if relu else inputs

  if init_zero:
    gamma_initializer = tf.zeros_initializer()
  else:
    gamma_initializer = tf.ones_initializer()

  if data_format == 'channels_first':
    axis = 1
  else:
    axis = 3

  inputs = tf.layers.batch_normalization(
      inputs=inputs,
      axis=axis,
      momentum=ssd_constants.BATCH_NORM_DECAY,
      epsilon=ssd_constants.BATCH_NORM_EPSILON,
      center=True,
      scale=True,
      training=is_training_bn,
      fused=True,
      gamma_initializer=gamma_initializer,
      name=name)

  if relu:
    inputs = tf.nn.relu(inputs)
  return inputs


def fixed_padding(inputs, kernel_size, data_format='channels_last'):
  """Pads the input along the spatial dimensions independently of input size.

  Args:
    inputs: `Tensor` of size `[batch, channels, height, width]` or
        `[batch, height, width, channels]` depending on `data_format`.
    kernel_size: `int` kernel size to be used for `conv2d` or max_pool2d`
        operations. Should be a positive integer.
    data_format: `str` either "channels_first" for `[batch, channels, height,
        width]` or "channels_last for `[batch, height, width, channels]`.

  Returns:
    A padded `Tensor` of the same `data_format` with size either intact
    (if `kernel_size == 1`) or padded (if `kernel_size > 1`).
  """
  pad_total = kernel_size - 1
  pad_beg = pad_total // 2
  pad_end = pad_total - pad_beg
  if data_format == 'channels_first':
    padded_inputs = tf.pad(
        inputs, [[0, 0], [0, 0], [pad_beg, pad_end], [pad_beg, pad_end]])
  else:
    padded_inputs = tf.pad(
        inputs, [[0, 0], [pad_beg, pad_end], [pad_beg, pad_end], [0, 0]])

  return padded_inputs


def space_to_depth_fixed_padding(inputs,
                                 kernel_size,
                                 data_format='channels_last',
                                 block_size=2):
  """Pads the input along the spatial dimensions independently of input size.

  Args:
    inputs: `Tensor` of size `[batch, channels, height, width]` or `[batch,
      height, width, channels]` depending on `data_format`.
    kernel_size: `int` kernel size to be used for `conv2d` or max_pool2d`
      operations. Should be a positive integer.
    data_format: `str` either "channels_first" for `[batch, channels, height,
      width]` or "channels_last for `[batch, height, width, channels]`.
    block_size: `int` block size for space-to-depth convolution.

  Returns:
    A padded `Tensor` of the same `data_format` with size either intact
    (if `kernel_size == 1`) or padded (if `kernel_size > 1`).
  """
  pad_total = kernel_size - 1
  pad_beg = (pad_total // 2 + 1) // block_size
  pad_end = (pad_total // 2) // block_size
  if data_format == 'channels_first':
    padded_inputs = tf.pad(
        inputs, [[0, 0], [0, 0], [pad_beg, pad_end], [pad_beg, pad_end]])
  else:
    padded_inputs = tf.pad(
        inputs, [[0, 0], [pad_beg, pad_end], [pad_beg, pad_end], [0, 0]])

  return padded_inputs


def conv2d_fixed_padding(inputs,
                         filters,
                         kernel_size,
                         strides,
                         use_fused_bn=False,
                         data_format='channels_last',
                         name=None):
  """Strided 2-D convolution with explicit padding.

  The padding is consistent and is based only on `kernel_size`, not on the
  dimensions of `inputs` (as opposed to using `tf.layers.conv2d` alone).

  Args:
    inputs: `Tensor` of size `[batch, channels, height_in, width_in]`.
    filters: `int` number of filters in the convolution.
    kernel_size: `int` size of the kernel to be used in the convolution.
    strides: `int` strides of the convolution.
    use_fused_bn: 'bool' whether use fused batch norm variables.
    data_format: `str` either "channels_first" for `[batch, channels, height,
        width]` or "channels_last for `[batch, height, width, channels]`.
    name: name of the Tensor.

  Returns:
    A `Tensor` of shape `[batch, filters, height_out, width_out]`.
  """
  if strides > 1:
    inputs = fixed_padding(inputs, kernel_size, data_format=data_format)

  return tf.layers.conv2d(
      inputs=inputs,
      filters=filters,
      kernel_size=kernel_size,
      strides=strides,
      padding=('SAME' if strides == 1 else 'VALID'),
      use_bias=True if use_fused_bn else False,
      kernel_initializer=tf.variance_scaling_initializer(),
      data_format=data_format,
      name=name)


def residual_block(inputs,
                   filters,
                   is_training_bn,
                   strides,
                   scope=None,
                   use_projection=False,
                   use_fused_bn=False,
                   data_format='channels_last'):
  """Standard building block for residual networks with BN after convolutions.

  Args:
    inputs: `Tensor` of size `[batch, channels, height, width]`.
    filters: `int` number of filters for the first two convolutions. Note that
        the third and final convolution will use 4 times as many filters.
    is_training_bn: `bool` for whether the model is in training.
    strides: `int` block stride. If greater than 1, this block will ultimately
        downsample the input.
    scope: scope of the block.
    use_projection: `bool` for whether this block should use a projection
        shortcut (versus the default identity shortcut). This is usually `True`
        for the first block of a block group, which may change the number of
        filters and the resolution.
    use_fused_bn: 'bool' whether use fused batch norm variables.
    data_format: `str` either "channels_first" for `[batch, channels, height,
        width]` or "channels_last for `[batch, height, width, channels]`.

  Returns:
    The output `Tensor` of the block.
  """
  shortcut = inputs
  if use_projection:
    # Projection shortcut in first layer to match filters and strides
    new_scope = re.sub(r'residul_block\d', 'downsample', scope)
    shortcut = conv2d_fixed_padding(
        inputs=inputs,
        filters=filters,
        kernel_size=1,
        strides=strides,
        use_fused_bn=use_fused_bn,
        data_format=data_format,
        name='%s_%d' % (new_scope, 1))
    shortcut = batch_norm_relu(
        shortcut,
        is_training_bn,
        relu=False,
        use_fused_bn=use_fused_bn,
        data_format=data_format,
        name='%s_bn%d' % (new_scope, 1))

  scope = scope.replace('stage2_residul_block1', 'stage2_residul_block1_1')

  inputs = conv2d_fixed_padding(
      inputs=inputs,
      filters=filters,
      kernel_size=3,
      strides=strides,
      use_fused_bn=use_fused_bn,
      data_format=data_format,
      name='%s_%d' % (scope, 1))
  inputs = batch_norm_relu(
      inputs,
      is_training_bn,
      use_fused_bn=use_fused_bn,
      data_format=data_format,
      name='%s_bn%d' % (scope, 1))

  if 'stage2_residul_block1_1' in scope:
    scope = scope.replace('stage2_residul_block1_1', 'stage2_residul_block1_2')
    number = 1
  else:
    number = 2

  inputs = conv2d_fixed_padding(
      inputs=inputs,
      filters=filters,
      kernel_size=3,
      strides=1,
      use_fused_bn=use_fused_bn,
      data_format=data_format,
      name='%s_%d' % (scope, number))
  inputs = batch_norm_relu(
      inputs,
      is_training_bn,
      relu=False,
      init_zero=True,
      use_fused_bn=use_fused_bn,
      data_format=data_format,
      name='%s_bn%d' % (scope, number))

  return tf.nn.relu(inputs + shortcut)


def block_group(inputs,
                filters,
                block_fn,
                blocks,
                strides,
                stage,
                is_training_bn,
                name,
                use_fused_bn=False,
                data_format='channels_last',
                use_projection=True):
  """Creates one group of blocks for the ResNet model.

  Args:
    inputs: `Tensor` of size `[batch, channels, height, width]`.
    filters: `int` number of filters for the first convolution of the layer.
    block_fn: `function` for the block to use within the model
    blocks: `int` number of blocks contained in the layer.
    strides: `int` stride to use for the first convolution of the layer. If
        greater than 1, this layer will downsample the input.
    stage: `int` stage number of the block.
    is_training_bn: `bool` for whether the model is training.
    name: `str`name for the Tensor output of the block layer.
    use_fused_bn: 'bool' whether use fused batch norm variables.
    data_format: `str` either "channels_first" for `[batch, channels, height,
        width]` or "channels_last for `[batch, height, width, channels]`.
    use_projection: `bool` for whether this block should use a projection
        shortcut (versus the default identity shortcut). This is usually `True`
        for the first block of a block group, which may change the number of
        filters and the resolution.

  Returns:
    The output `Tensor` of the block layer.
  """
  # Only the first block per block_group uses projection shortcut and strides.
  inputs = block_fn(
      inputs,
      filters,
      is_training_bn,
      strides,
      scope='%s%d/stage%d_residul_block1' % (name, 1, stage),
      use_projection=use_projection,
      use_fused_bn=use_fused_bn,
      data_format=data_format)

  for i in range(1, blocks):
    inputs = block_fn(
        inputs,
        filters,
        is_training_bn,
        1,
        scope='%s%d/stage%d_residul_block%d' % (name, i + 1, stage, i + 1),
        use_fused_bn=use_fused_bn,
        data_format=data_format)

  return tf.identity(inputs, name)


def conv0_space_to_depth(inputs,
                         use_fused_bn=False,
                         data_format='channels_last'):
  """Strided 2-D convolution with explicit padding.

  The padding is consistent and is based only on `kernel_size`, not on the
  dimensions of `inputs` (as opposed to using `tf.layers.conv2d` alone).

  Args:
    inputs: `Tensor` of size `[batch, height_in, width_in, channels]`.
    use_fused_bn: 'bool' whether use fused batch norm variables.
    data_format: `str` either "channels_first" for `[batch, channels, height,
      width]` or "channels_last for `[batch, height, width, channels]`.

  Returns:
    A `Tensor` with the same type as `inputs`.
  """
  # Create the conv0 kernel w.r.t. the original image size. (no space-to-depth).
  filters = 64
  kernel_size = 7
  space_to_depth_block_size = ssd_constants.SPACE_TO_DEPTH_BLOCK_SIZE
  strides = 2
  conv0 = tf.layers.Conv2D(
      filters=filters,
      kernel_size=kernel_size,
      strides=2,
      padding=('SAME' if strides == 1 else 'VALID'),
      use_bias=True if use_fused_bn else False,
      kernel_initializer=tf.variance_scaling_initializer(),
      data_format=data_format,
      name='conv1_1')
  # Use the image size without space-to-depth transform as the input of conv0.
  batch_size, h, w, channel = inputs.get_shape().as_list()
  conv0.build([
      batch_size, h * space_to_depth_block_size, w * space_to_depth_block_size,
      channel / (space_to_depth_block_size**2)
  ])

  kernel = conv0.weights[0]
  # [7, 7, 3, 64] --> [8, 8, 3, 64]
  kernel = tf.pad(
      kernel,
      paddings=tf.constant([[1, 0], [1, 0], [0, 0], [0, 0]]),
      mode='CONSTANT',
      constant_values=0.)
  # Transform kernel follows the space-to-depth logic: http://shortn/_9YvHW96xPJ
  kernel = tf.reshape(
      kernel,
      [4, space_to_depth_block_size, 4, space_to_depth_block_size, 3, filters])
  kernel = tf.transpose(kernel, [0, 2, 1, 3, 4, 5])
  kernel = tf.reshape(kernel, [4, 4, int(channel), filters])
  kernel = tf.cast(kernel, inputs.dtype)

  inputs = space_to_depth_fixed_padding(inputs, kernel_size, data_format,
                                        space_to_depth_block_size)

  outputs = tf.nn.conv2d(
      input=inputs,
      filter=kernel,
      strides=[1, 1, 1, 1],
      padding='VALID',
      data_format='NHWC' if data_format == 'channels_last' else 'NCHW',
      name='conv1_1')
  if use_fused_bn:
    # The additional bias is used as the batch norm is fused into the conv
    # layer.
    return tf.nn.bias_add(
        outputs, tf.cast(conv0.weights[1], outputs.dtype), data_format='NHWC')
  else:
    return outputs


def resnet_v1_generator(block_fn, layers, params, data_format='channels_last'):
  """Generator of ResNet v1 model with classification layers removed.

    Our actual ResNet network.  We return the output of c2, c3,c4,c5
    N.B. batch norm is always run with trained parameters, as we use very small
    batches when training the object layers.

  Args:
    block_fn: `function` for the block to use within the model. Either
      `residual_block` or `bottleneck_block`.
    layers: list of 4 `int`s denoting the number of blocks to include in each of
      the 4 block groups. Each group consists of blocks that take inputs of the
      same resolution.
    params: params of the model, a dict.
    data_format: `str` either "channels_first" for `[batch, channels, height,
      width]` or "channels_last for `[batch, height, width, channels]`.

  Returns:
    Model `function` that takes in `inputs` and `is_training` and returns the
    output `Tensor` of the ResNet model.
  """
  def model(inputs, is_training_bn=False):
    """Creation of the model graph."""
    with tf.variable_scope('conv1'):
      if params['conv0_space_to_depth']:
        # conv0 uses space-to-depth transform for TPU performance.
        inputs = conv0_space_to_depth(
            inputs=inputs,
            use_fused_bn=params['use_fused_bn'],
            data_format=data_format)
      else:
        inputs = conv2d_fixed_padding(
            inputs=inputs,
            filters=64,
            kernel_size=7,
            strides=2,
            use_fused_bn=params['use_fused_bn'],
            data_format=data_format,
            name='conv1_1')
      inputs = tf.identity(inputs, 'conv1')
      inputs = batch_norm_relu(
          inputs,
          is_training_bn,
          use_fused_bn=params['use_fused_bn'],
          data_format=data_format,
          name='conv1_bn1')

    inputs = tf.layers.max_pooling2d(
        inputs=inputs,
        pool_size=3,
        strides=2,
        padding='SAME',
        data_format=data_format)
    inputs = tf.identity(inputs, 'initial_max_pool')

    c2 = block_group(
        inputs=inputs,
        filters=64,
        blocks=layers[0],
        strides=1,
        stage=1,
        block_fn=block_fn,
        is_training_bn=is_training_bn,
        name='stage1_residul_block',
        use_fused_bn=params['use_fused_bn'],
        data_format=data_format,
        use_projection=False)
    c3 = block_group(
        inputs=c2,
        filters=128,
        blocks=layers[1],
        strides=2,
        stage=2,
        block_fn=block_fn,
        is_training_bn=is_training_bn,
        name='stage2_residul_block',
        use_fused_bn=params['use_fused_bn'],
        data_format=data_format)
    c4 = block_group(
        inputs=c3,
        filters=256,
        blocks=layers[2],
        strides=1,
        stage=3,
        block_fn=block_fn,
        is_training_bn=is_training_bn,
        name='stage3_residul_block',
        use_fused_bn=params['use_fused_bn'],
        data_format=data_format)
    return c2, c3, c4

  return model


def resnet_v1(resnet_depth, params, data_format='channels_last'):
  """Returns the ResNet model for a given size and number of output classes."""
  model_params = {
      34: {'block': residual_block, 'layers': [3, 4, 6, 3]}
  }

  if resnet_depth not in model_params:
    raise ValueError('Not a valid resnet_depth:', resnet_depth)

  resnet_params = model_params[resnet_depth]
  return resnet_v1_generator(resnet_params['block'], resnet_params['layers'],
                             params, data_format)


def class_net(images, level, num_classes):
  """Class prediction network for SSD."""
  return tf.layers.conv2d(
      images,
      num_classes * ssd_constants.NUM_DEFAULTS_BY_LEVEL[level],
      strides=(3, 3),
      kernel_size=(3, 3),
      padding='same',
      activation=None,
      name='cls_%d' % (level - 3),
  )


def box_net(images, level):
  """Box regression network for SSD."""
  return tf.layers.conv2d(
      images,
      4 * ssd_constants.NUM_DEFAULTS_BY_LEVEL[level],
      strides=(3, 3),
      kernel_size=(3, 3),
      padding='same',
      activation=None,
      name='loc_%d' % (level - 3),
  )


def ssd(features, params, is_training_bn=False):
  """SSD classification and regression model."""
  # upward layers
  with tf.variable_scope('ssd1200'):
    resnet_fn = resnet_v1(ssd_constants.RESNET_DEPTH, params)
    _, _, u4 = resnet_fn(features, is_training_bn)

  with tf.variable_scope('ssd1200'):
    with tf.variable_scope('additional_layers'):
      feats = {}
      # output channels for mlperf logging.
      out_channels = [256]
      feats[3] = u4
      feats[4] = tf.layers.conv2d(
          feats[3],
          filters=256,
          kernel_size=(1, 1),
          padding='same',
          activation=tf.nn.relu,
          name='conv7/conv7_1')
      feats[4] = tf.layers.conv2d(
          feats[4],
          filters=512,
          strides=(2, 2),
          kernel_size=(3, 3),
          padding='same',
          activation=tf.nn.relu,
          name='conv7/conv7_2')
      out_channels.append(512)
      feats[5] = tf.layers.conv2d(
          feats[4],
          filters=256,
          kernel_size=(1, 1),
          padding='same',
          activation=tf.nn.relu,
          name='conv8/conv8_1')
      feats[5] = tf.layers.conv2d(
          feats[5],
          filters=512,
          strides=(2, 2),
          kernel_size=(3, 3),
          padding='same',
          activation=tf.nn.relu,
          name='conv8/conv8_2')
      out_channels.append(512)
      feats[6] = tf.layers.conv2d(
          feats[5],
          filters=128,
          kernel_size=(1, 1),
          padding='same',
          activation=tf.nn.relu,
          name='conv9/conv9_1')
      feats[6] = tf.layers.conv2d(
          feats[6],
          filters=256,
          strides=(2, 2),
          kernel_size=(3, 3),
          padding='same',
          activation=tf.nn.relu,
          name='conv9/conv9_2')
      out_channels.append(256)
      feats[7] = tf.layers.conv2d(
          feats[6],
          filters=128,
          kernel_size=(1, 1),
          padding='same',
          activation=tf.nn.relu,
          name='conv10/conv10_1')
      feats[7] = tf.layers.conv2d(
          feats[7],
          filters=256,
          strides=(2, 2),
          kernel_size=(3, 3),
          padding='valid',
          activation=tf.nn.relu,
          name='conv10/conv10_2')
      out_channels.append(256)
      feats[8] = tf.layers.conv2d(
          feats[7],
          filters=128,
          kernel_size=(1, 1),
          padding='same',
          activation=tf.nn.relu,
          name='conv11/conv11_1')
      feats[8] = tf.layers.conv2d(
          feats[8],
          filters=256,
          kernel_size=(3, 3),
          padding='valid',
          activation=tf.nn.relu,
          name='conv11/conv11_2')
      out_channels.append(256)

    class_outputs = {}
    box_outputs = {}
    min_level = ssd_constants.MIN_LEVEL
    max_level = ssd_constants.MAX_LEVEL
    num_classes = ssd_constants.NUM_CLASSES

    with tf.variable_scope('multibox_head', reuse=tf.AUTO_REUSE):
      for level in range(min_level, max_level + 1):
        class_outputs[level] = class_net(
            feats[level], level, num_classes)

      for level in range(min_level, max_level + 1):
        box_outputs[level] = box_net(
            feats[level], level)

  return class_outputs, box_outputs
