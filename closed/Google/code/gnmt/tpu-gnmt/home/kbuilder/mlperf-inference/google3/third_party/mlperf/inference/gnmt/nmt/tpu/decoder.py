# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
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
"""Seq2seq layer operations for use in neural networks."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import abc
import six
import tensorflow as tf

from tensorflow.python.ops import control_flow_util
from tensorflow.python.ops import rnn
from tensorflow.python.ops import rnn_cell_impl


__all__ = ["Decoder", "dynamic_decode"]


_transpose_batch_time = rnn._transpose_batch_time  # pylint: disable=protected-access
_zero_state_tensors = rnn_cell_impl._zero_state_tensors  # pylint: disable=protected-access


@six.add_metaclass(abc.ABCMeta)
class Decoder(object):
  """An RNN Decoder abstract interface object.

  Concepts used by this interface:
  - `inputs`: (structure of) tensors and TensorArrays that is passed as input to
    the RNNCell composing the decoder, at each time step.
  - `state`: (structure of) tensors and TensorArrays that is passed to the
    RNNCell instance as the state.
  - `finished`: boolean tensor telling whether each sequence in the batch is
    finished.
  - `outputs`: Instance of BasicDecoderOutput. Result of the decoding, at each
    time step.
  """

  @property
  def batch_size(self):
    """The batch size of input values."""
    raise NotImplementedError

  @property
  def output_size(self):
    """A (possibly nested tuple of...) integer[s] or `TensorShape` object[s]."""
    raise NotImplementedError

  @property
  def output_dtype(self):
    """A (possibly nested tuple of...) dtype[s]."""
    raise NotImplementedError

  @abc.abstractmethod
  def initialize(self, name=None):
    """Called before any decoding iterations.

    This methods must compute initial input values and initial state.

    Args:
      name: Name scope for any created operations.

    Returns:
      `(finished, initial_inputs, initial_state)`: initial values of
      'finished' flags, inputs and state.
    """
    raise NotImplementedError

  @abc.abstractmethod
  def step(self, time, inputs, state, name=None):
    """Called per step of decoding (but only once for dynamic decoding).

    Args:
      time: Scalar `int32` tensor. Current step number.
      inputs: RNNCell input (possibly nested tuple of) tensor[s] for this time
        step.
      state: RNNCell state (possibly nested tuple of) tensor[s] from previous
        time step.
      name: Name scope for any created operations.

    Returns:
      `(outputs, next_state, next_inputs, finished)`: `outputs` is an object
      containing the decoder output, `next_state` is a (structure of) state
      tensors and TensorArrays, `next_inputs` is the tensor that should be used
      as input for the next step, `finished` is a boolean tensor telling whether
      the sequence is complete, for each sequence in the batch.
    """
    raise NotImplementedError

  def finalize(self, outputs, final_state, sequence_lengths):
    raise NotImplementedError

  @property
  def tracks_own_finished(self):
    """Describes whether the Decoder keeps track of finished states.

    Most decoders will emit a true/false `finished` value independently
    at each time step.  In this case, the `dynamic_decode` function keeps track
    of which batch entries are already finished, and performs a logical OR to
    insert new batches to the finished set.

    Some decoders, however, shuffle batches / beams between time steps and
    `dynamic_decode` will mix up the finished state across these entries because
    it does not track the reshuffle across time steps.  In this case, it is
    up to the decoder to declare that it will keep track of its own finished
    state by setting this property to `True`.

    Returns:
      Python bool.
    """
    return False


def _create_zero_outputs(size, dtype):
  """Create a zero outputs Tensor structure."""
  def _create(s, d):
    return tf.zeros(s, d)

  return tf.contrib.framework.nest.map_structure(_create, size, dtype)


def dynamic_decode(decoder,
                   impute_finished=False,
                   maximum_iterations=None,
                   parallel_iterations=32,
                   swap_memory=False,
                   scope=None):
  """Perform dynamic decoding with `decoder`.

  Calls initialize() once and step() repeatedly on the Decoder object.

  Args:
    decoder: A `Decoder` instance.
    impute_finished: Python boolean.  If `True`, then states for batch
      entries which are marked as finished get copied through and the
      corresponding outputs get zeroed out.  This causes some slowdown at
      each time step, but ensures that the final state and outputs have
      the correct values and that backprop ignores time steps that were
      marked as finished.
    maximum_iterations: `int32` scalar, maximum allowed number of decoding
       steps.  Default is `None` (decode until the decoder is fully done).
    parallel_iterations: Argument passed to `tf.while_loop`.
    swap_memory: Argument passed to `tf.while_loop`.
    scope: Optional variable scope to use.

  Returns:
    `(final_outputs, final_state, final_sequence_lengths)`.

  Raises:
    TypeError: if `decoder` is not an instance of `Decoder`.
    ValueError: if `maximum_iterations` is provided but is not a scalar.
  """
  if not isinstance(decoder, Decoder):
    raise TypeError("Expected decoder to be type Decoder, but saw: %s" %
                    type(decoder))

  with tf.variable_scope(scope, "decoder") as varscope:
    # Determine context types.
    ctxt = tf.get_default_graph()._get_control_flow_context()  # pylint: disable=protected-access
    is_xla = control_flow_util.GetContainingXLAContext(ctxt) is not None
    in_while_loop = (
        control_flow_util.GetContainingWhileContext(ctxt) is not None)
    # Properly cache variable values inside the while_loop.
    # Don't set a caching device when running in a loop, since it is possible
    # that train steps could be wrapped in a tf.while_loop. In that scenario
    # caching prevents forward computations in loop iterations from re-reading
    # the updated weights.
    if not tf.executing_eagerly() and not in_while_loop:
      if varscope.caching_device is None:
        varscope.set_caching_device(lambda op: op.device)

    if maximum_iterations is not None:
      maximum_iterations = tf.convert_to_tensor(
          maximum_iterations, dtype=tf.int32, name="maximum_iterations")
      if maximum_iterations.get_shape().ndims != 0:
        raise ValueError("maximum_iterations must be a scalar")

    initial_finished, initial_inputs, initial_state = decoder.initialize()

    zero_outputs = _create_zero_outputs(decoder.output_size,
                                        decoder.output_dtype)

    if is_xla and maximum_iterations is None:
      raise ValueError("maximum_iterations is required for XLA compilation.")
    if maximum_iterations is not None:
      initial_finished = tf.logical_or(
          initial_finished, 0 >= maximum_iterations)
    initial_sequence_lengths = tf.zeros_like(
        initial_finished, dtype=tf.int32)
    initial_time = tf.constant(0, dtype=tf.int32)

    dynamic_size = maximum_iterations is None or not is_xla

    def _create_ta(s, d):
      return tf.TensorArray(
          dtype=d,
          size=0 if dynamic_size else maximum_iterations,
          dynamic_size=dynamic_size,
          element_shape=s)

    initial_outputs_ta = tf.contrib.framework.nest.map_structure(
        _create_ta, decoder.output_size, decoder.output_dtype)

    def condition(unused_time, unused_outputs_ta, unused_state, unused_inputs,
                  finished, unused_sequence_lengths):
      return tf.logical_not(tf.reduce_all(finished))

    def body(time, outputs_ta, state, inputs, finished, sequence_lengths):
      """Internal while_loop body.

      Args:
        time: scalar int32 tensor.
        outputs_ta: structure of TensorArray.
        state: (structure of) state tensors and TensorArrays.
        inputs: (structure of) input tensors.
        finished: bool tensor (keeping track of what's finished).
        sequence_lengths: int32 tensor (keeping track of time of finish).

      Returns:
        `(time + 1, outputs_ta, next_state, next_inputs, next_finished,
          next_sequence_lengths)`.
        ```
      """
      (next_outputs, decoder_state, next_inputs,
       decoder_finished) = decoder.step(time, inputs, state)
      if decoder.tracks_own_finished:
        next_finished = decoder_finished
      else:
        next_finished = tf.logical_or(decoder_finished, finished)
      next_sequence_lengths = tf.where(
          tf.logical_not(finished),
          tf.fill(tf.shape(sequence_lengths), time + 1),
          sequence_lengths)

      tf.contrib.framework.nest.assert_same_structure(state, decoder_state)
      tf.contrib.framework.nest.assert_same_structure(outputs_ta, next_outputs)
      tf.contrib.framework.nest.assert_same_structure(inputs, next_inputs)

      # Zero out output values past finish
      if impute_finished:
        emit = tf.contrib.framework.nest.map_structure(
            lambda out, zero: tf.where(finished, zero, out),
            next_outputs,
            zero_outputs)
      else:
        emit = next_outputs

      # Copy through states past finish
      def _maybe_copy_state(new, cur):
        # TensorArrays and scalar states get passed through.
        if isinstance(cur, tf.TensorArray):
          pass_through = True
        else:
          new.set_shape(cur.shape)
          pass_through = (new.shape.ndims == 0)
        return new if pass_through else tf.where(finished, cur, new)

      if impute_finished:
        next_state = tf.contrib.framework.nest.map_structure(
            _maybe_copy_state, decoder_state, state)
      else:
        next_state = decoder_state

      outputs_ta = tf.contrib.framework.nest.map_structure(
          lambda ta, out: ta.write(time, out), outputs_ta, emit)
      return (time + 1, outputs_ta, next_state, next_inputs, next_finished,
              next_sequence_lengths)

    res = tf.while_loop(
        condition,
        body,
        loop_vars=(
            initial_time,
            initial_outputs_ta,
            initial_state,
            initial_inputs,
            initial_finished,
            initial_sequence_lengths,
        ),
        parallel_iterations=parallel_iterations,
        maximum_iterations=maximum_iterations,
        swap_memory=swap_memory)

    final_outputs_ta = res[1]
    final_state = res[2]
    final_sequence_lengths = res[5]

    final_outputs = tf.contrib.framework.nest.map_structure(
        lambda ta: ta.stack(), final_outputs_ta)

    try:
      final_outputs, final_state = decoder.finalize(
          final_outputs, final_state, final_sequence_lengths)
    except NotImplementedError:
      pass

  return final_state.pred_ids
