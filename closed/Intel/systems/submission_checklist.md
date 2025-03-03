# MLPerf Inference 0.5 Self-Certification Checklist

Name of Certifying Engineer(s): Christine Cheng, Haim Barad

Email of Certifying Engineer(s): christine.cheng@intel.com, haim.barad@intel.com	

Name of System(s) Under Test: CLX-AP 2S, DELL ICL i3, CLX 9282 2S

Division (check one):
- [ ] Open
- [X] Closed

Category (check one):
- [X] Available
- [X] Preview
- [ ] Research, Development, and Internal (RDI)

Benchmark (check one):
- [X] MobileNet
- [X] SSD-MobileNet
- [X] ResNet
- [ ] SSD-1200
- [ ] NMT
- [ ] Other, please specify:

Please fill in the following tables adding lines as necessary:
97%-tile latency is required for NMT only. 99%-tile is required for all other models.

### Single Stream Results Table
| SUT Name | Benchmark | Query Count | Accuracy |
|----------|-----------|-------------|----------|
| CLX 9282 2S| ResNet    | 50000       | 76.124%  |
| CLX 9282 2S| MobileNet | 50000       | 70.550%  |
| CLX 9282 2S| SSD Small | 256       | 22.627%  |
| DELL ICL i3| ResNet  | 1024      | 76.234%  |
| DELL ICL i3| MobileNet | 1024    | 71.528% |
| DELL ICL i3| SSD Small | 256     | 22.627%  |




### Server Results Table
| SUT Name | Benchmark | Query Count | Accuracy | 97%-tile Latency | 99%-tile Latency |
|----------|-----------|-------------|----------|------------------|------------------|
| CLX 9282 2S| ResNet    | 50000       | 76.124%  |                 |14796624      |
| NNPI-1000 x2| ResNet    | 1024      | 75.720%  |                 |13249895      |
| CLX 9282 2S| MobileNet | 50000       | 70.550%  |                 |6565300      |
| CLX 9282 2S| SSD Small | 256       | 22.627%  |               |7416184      |


### Offline Results Table
| SUT Name | Benchmark | Query Count | Accuracy |
|----------|-----------|-------------|----------|
| CLX 9282 2S| ResNet    | 50000       | 76.124%  |
| CLX 9282 2S| MobileNet | 50000       | 70.550%  |
| CLX 9282 2S| SSD Small | 256        | 22.627%  |
| DELL ICL i3| ResNet  | 1024      | 76.400%  |
| DELL ICL i3| MobileNet | 1024    | 71.566% |
| DELL ICL i3| SSD Small | 256     | 22.627%  |
| NNPI-1000 x2| ResNet    | 1024   | 75.720%  |


Scenario (check all that apply):
- [X] Single-Stream
- [ ] Multi-Stream
- [X] Server
- [X] Offline

For each SUT, does the submission meet the latency target for each
combination of benchmark and scenario? (check all that apply)
- [X] Yes (Single-Stream and Offline no requirements)
- [ ] Yes (MobileNet x Multi-Stream 50 ms @ 99%)
- [X] Yes (MobileNet x Server 10 ms @ 99%)
- [ ] Yes (SSD-MobileNet x Multi-Stream 50 ms @ 99%)
- [X] Yes (SSD-MobileNet x Server 10 ms @ 99%)
- [ ] Yes (ResNet x Multi-Stream 50 ms @ 99%)
- [X] Yes (ResNet x Server 15 ms @ 99%)
- [ ] Yes (SSD-1200 x Multi-Stream 66 ms @ 99%).
- [ ] Yes (SSD-1200 x Server 100 ms @ 99%)
- [ ] Yes (NMT x Multi-Stream 100 ms @ 97%)
- [ ] Yes (NMT x Server 250 ms @ 97%)
- [ ] No

For each SUT, is the appropriate minimum number of queries or samples
met, depending on the Scenario x Benchmark? (check all that apply)
- [X] Yes (Single-Stream 1,024 queries)
- [X] Yes (Offline 24,576 samples)
- [ ] Yes (NMT Server and Multi-Stream 90,112 queries)
- [X] Yes (Image Models Server and Multi-Stream 270,336 queries)
- [ ] No

For each SUT and scenario, is the benchmark accuracy target met?
(check all that apply)
- [X] Yes (MobileNet 71.68% x 98%)
- [X] Yes (SSD-MobileNet 0.22 mAP x 99%)
- [X] Yes (ResNet 76.46% x 99%)
- [ ] Yes (SSD-1200 0.20 mAP x 99%)
- [ ] Yes (NMT 23.9 BLEU x 99%)
- [ ] No


For each SUT and scenario, did the submission run on the whole
validation set in accuracy mode? (check one)
- [X] Yes
- [ ] No

How many samples are loaded into the QSL in performance mode?
- resnet: 1024 - 50000  
- mobilenet: 1024 - 50000  
- ssd-small: 256


For each SUT and scenario, does the number of loaded samples in the
QSL in performance mode meet the minimum requirement?  (check all that
apply)
- [X] Yes (ResNet and MobileNet 1,024 samples)
- [X] Yes (SSD-MobileNet 256 samples)
- [ ] Yes (SSD-1200 64 samples)
- [ ] Yes (NMT 3,903,900 samples)
- [ ] No

For each SUT and scenario, is the experimental duration greater than
or equal to 60 seconds?  (check one)
- [X] Yes
- [ ] No

Does the submission use LoadGen? (check one)
- [X] Yes
- [ ] No

Is your loadgen commit from one of these allowed commit hashes?
- [X] 61220457dec221ed1984c62bd9d382698bd71bc6
- [ ] 5684c11e3987b614aae830390fa0e92f56b7e800
- [X] 55c0ea4e772634107f3e67a6d0da61e6a2ca390d
- [ ] d31c18fbd9854a4f1c489ca1bc4cd818e48f2bc5
- [ ] 1d0e06e54a7d763cf228bdfd8b1e987976e4222f
- [X] Other, please specify:413dbabcb30dc2ee1fe42e7b8090b37e8144617d (Oct 9)

Do you have any additional change to Loadgen? (check one)
- [ ] Yes, please specify:
- [X] No

Does the submission run the same code in accuracy and performance
modes? (check one)
- [X] Yes
- [ ] No

Where is the LoadGen trace stored? (check one)
- [X] Host DRAM
- [ ] Other, please specify:

For the submitted result, what is the QSL random number generator seed?
- [X] 0x2b7e151628aed2a6ULL (3133965575612453542)
- [ ] Other, please specify:

For the submitted results, what is the sample index random number generator seed?
- [X] 0x093c467e37db0c7aULL (665484352860916858)
- [ ] Other, please specify:

For the submitted results, what is the schedule random number generator seed?
- [X] 0x3243f6a8885a308dULL (3622009729038561421)
- [ ] Other, please specify:

For each SUT and scenario, is the submission run the correct number of
times for the relevant scenario? (check one)
- [X] Yes (Accuracy 1x Performance 1x Single-Stream, Multi-Stream,
Offline)
- [X] Yes (Accuracy 1x Performance 5x Server)
- [ ] No

Are the weights calibrated using data outside of the calibration set?
(check one)
- [ ] Yes
- [X] No

What untimed pre-processing does the submission use? (check all that apply)
- [X] Resize
- [X] Reorder channels or transpose
- [ ] Pad
- [X] A single crop
- [X] Mean subtraction and normalization
- [X] Convert to whitelisted format
- [ ] No pre-processing
- [ ] Other, please specify:

What numerics does the submission use? (check all that apply)
- [ ] INT4
- [X] INT8
- [ ] INT16
- [ ] UINT8
- [ ] UINT16
- [ ] FP11
- [X] FP16
- [ ] BF16
- [ ] FP32
- [ ] Other, please specify:

Which of the following techniques does the submission use? (check all
that apply)
- [ ] Wholesale weight replacement
- [ ] Weight supplements
- [ ] Discarding non-zero weight elements
- [ ] Pruning
- [ ] Caching queries
- [ ] Caching responses
- [ ] Caching intermediate computations
- [ ] Modifying weights during the timed portion of an inference run
- [ ] Weight quantization algorithms that are similar in size to the
non-zero weights they produce
- [ ] Hard coding the total number of queries
- [ ] Techniques that boost performance for fixed length experiments but
are inapplicable to long-running services except in the offline
scenario
- [ ] Using knowledge of the LoadGen implementation to predict upcoming
lulls or spikes in the server scenario
- [ ] Treating beams in a beam search differently. For example,
employing different precision for different beams
- [ ] Changing the number of beams per beam search relative to the reference
- [ ] Incorporating explicit statistical information about the performance or accuracy sets
- [ ] Techniques that take advantage of upsampled images.
- [ ] Techniques that only improve performance when there are identical samples in a query.
- [X] None of the above

Is the submission congruent with all relevant MLPerf rules?
- [X] Yes
- [ ] No

For each SUT, does the submission accurately reflect the real-world
performance of the SUT?
- [X] Yes
- [ ] No

