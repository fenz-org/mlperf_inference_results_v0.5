#!/usr/bin/python

# Copyright (c) 2019, NVIDIA CORPORATION.  All rights reserved.
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

# Script to dump TensorFlow weights in TRT v1 and v2 dump format.
# The V1 format is for TensorRT 4.0. The V2 format is for TensorRT 4.0 and later.

import sys
import struct
import argparse
try:
    import tensorflow as tf
    from tensorflow.python import pywrap_tensorflow
except ImportError as err:
    sys.stderr.write("""Error: Failed to import module ({})""".format(err))
    sys.exit()

parser = argparse.ArgumentParser(description='TensorFlow Weight Dumper')

parser.add_argument('-m', '--model', required=True, help='The checkpoint file basename, example basename(model.ckpt-766908.data-00000-of-00001) -> model.ckpt-766908')
parser.add_argument('-o', '--output', required=True, help='The weight file to dump all the weights to.')

opt = parser.parse_args()


print ("Outputting the trained weights in TensorRT's wts v2 format. This format is documented as:")
print ("Line 0: <number of buffers in the file>")
print ("Line 1-Num: [buffer name] [buffer type] [(buffer shape{e.g. (1, 2, 3)}] <buffer shaped size bytes of data>")

inputbase = opt.model
outputbase = opt.output

def getTRTType(tensor):
    if tf.as_dtype(tensor.dtype) == tf.float32:
        return 0
    if tf.as_dtype(tensor.dtype) == tf.float16:
        return 1
    if tf.as_dtype(tensor.dtype) == tf.int8:
        return 2
    if tf.as_dtype(tensor.dtype) == tf.int32:
        return 3
    print ("Tensor data type of %s is not supported in TensorRT"%(tensor.dtype))
    sys.exit();

try:
   # Open output file
    outputFileName = outputbase + ".wts"
    outputFile = open(outputFileName, 'wb')

    # read vars from checkpoint
    reader = pywrap_tensorflow.NewCheckpointReader(inputbase)
    var_to_shape_map = reader.get_variable_to_shape_map()

    # Record count of weights
    count = 0
    for key in sorted(var_to_shape_map):
        count += 1
    outputFile.write(bytes("%s\n"%(count), 'utf-8'))

    # Dump the weights
    for key in sorted(var_to_shape_map):
        tensor = reader.get_tensor(key)
        file_key = key.replace('/','_')
        typeOfElem = getTRTType(tensor)
        val = tensor.shape
        print ("%s %s %s " % (file_key, typeOfElem, val))
        flat_tensor = tensor.flatten()
        outputFile.write(bytes("%s 0 %s "%(file_key, val), 'utf-8'))
        outputFile.write(flat_tensor.tobytes())
        outputFile.write(bytes("\n", 'utf-8'))
    outputFile.close()

except Exception as e:  # pylint: disable=broad-except
    print (str(e))
    if "corrupted compressed block contents" in str(e):
        print ("It's likely that your checkpoint file has been compressed "
                "with SNAPPY.")
        if ("Data loss" in str(e) and
                (any([e in inputbase for e in [".index", ".meta", ".data"]]))):
            proposed_file = ".".join(inputbase.split(".")[0:-1])
            v2_file_error_template = """
           It's likely that this is a V2 checkpoint and you need to provide the filename
           *prefix*.  Try removing the '.' and extension.  Try:
           inspect checkpoint --file_name = {}"""
            print(v2_file_error_template.format(proposed_file))
