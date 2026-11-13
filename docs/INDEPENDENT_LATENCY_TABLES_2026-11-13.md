# Independent latency sweep: numerical tables

Evaluation30, means of three paired orders. Every modified tool duration is synthetic.
The original sweep retains speculative-only caching. Common-cache controls are a separate, explicit comparison below.
Each row specifies its own quota, workers, lifetime and worker release rule; comparisons never cross those settings.
Latency reduction = 100 × (1 − mean speculative latency / mean baseline latency).
Throughput gain = 100 × (mean per-order tasks/finish time / corresponding baseline − 1).
The two percentages differ. All-work finish includes background drain.

## Exact no-quota per-question opportunity

| Search duration | A latency s | Recorded gate, age 0: s / reduction | Recorded gate, age 1: s / reduction | F perfect predictor: s / reduction | G zero generation: s / reduction |
|---|---:|---:|---:|---:|---:|
| native | 10.543499 | 10.399114 / +1.369% | 10.371852 / +1.628% | 10.370637 / +1.640% | 9.116628 / +13.533% |
| scale2 | 12.693623 | 12.156227 / +4.234% | 12.198995 / +3.897% | 11.811440 / +6.950% | 10.230419 / +19.405% |
| scale5 | 19.143994 | 17.376261 / +9.234% | 17.376261 / +9.234% | 15.644071 / +18.282% | 13.958901 / +27.085% |
| scale10 | 29.894612 | 26.110516 / +12.658% | 26.110516 / +12.658% | 22.025005 / +26.324% | 20.320172 / +32.027% |
| fixed1 | 11.426709 | 11.163496 / +2.303% | 11.130162 / +2.595% | 11.109987 / +2.772% | 9.564072 / +16.301% |
| fixed2 | 14.460042 | 13.496834 / +6.661% | 13.499077 / +6.646% | 12.936635 / +10.535% | 11.282761 / +21.973% |
| fixed5 | 23.560042 | 20.596834 / +12.577% | 20.599077 / +12.568% | 18.336635 / +22.171% | 16.553220 / +29.740% |
| fixed10 | 38.726709 | 32.430168 / +16.259% | 32.432410 / +16.253% | 27.336635 / +29.411% | 25.386554 / +34.447% |

E columns above exhaust every useful subset separately per task; these are exact mean-latency optima in the no-quota architecture. They do not assert an exact quota-constrained batch optimum.
F predicts the next required Search, pays each saved source generation duration, generates on cache reuse, never recursively predicts from speculative dispatch, and uses matching required tool service times.
G removes only generation duration in that same one-step architecture. Its no-quota mean is an upper reference for that architecture. The eager G policy under binding quotas is not a globally optimized upper bound.

## Four-worker answer-release comparisons

Original candidate lifetime, no extra duplicate suppression for B/C/D/E; one persistent quota. E is exact at native timings (nine bits), otherwise a feasible best-found pipeline gate.

| Quota | Search duration | Policy | Mean answer s | All answers s | All work s | All-work throughput gain | E exact? |
|---|---|---|---:|---:|---:|---:|---|
| 10000/1s | native | A_none | 10.543 | 163.647 | 163.647 | +0.000% |  |
| 10000/1s | native | B_ungated | 10.399 | 163.283 | 163.666 | -0.023% |  |
| 10000/1s | native | C_reserve | 10.399 | 163.283 | 163.666 | -0.023% |  |
| 10000/1s | native | D_jev_own | 10.510 | 163.647 | 164.030 | -0.234% |  |
| 10000/1s | native | D_jev_all | 10.510 | 163.647 | 164.030 | -0.234% |  |
| 10000/1s | native | E_post | 10.399 | 163.283 | 163.666 | -0.023% | True |
| 10000/1s | native | E_pipeline | 10.399 | 163.283 | 163.283 | +0.212% | True |
| 10000/1s | native | F_full_generation | 10.371 | 162.580 | 162.963 | +0.408% |  |
| 10000/1s | native | G_zero_overhead | 9.117 | 159.871 | 159.871 | +2.324% |  |
| 10000/1s | scale2 | A_none | 12.694 | 169.096 | 169.096 | +0.000% |  |
| 10000/1s | scale2 | B_ungated | 12.156 | 167.669 | 168.884 | +0.074% |  |
| 10000/1s | scale2 | C_reserve | 12.156 | 167.669 | 168.884 | +0.074% |  |
| 10000/1s | scale2 | D_jev_own | 12.261 | 167.789 | 167.829 | +0.710% |  |
| 10000/1s | scale2 | D_jev_all | 12.261 | 167.789 | 167.829 | +0.710% |  |
| 10000/1s | scale2 | E_post | 12.156 | 167.669 | 167.669 | +0.802% | False |
| 10000/1s | scale2 | E_pipeline | 12.156 | 167.669 | 167.669 | +0.802% | False |
| 10000/1s | scale2 | F_full_generation | 11.811 | 166.546 | 166.546 | +1.491% |  |
| 10000/1s | scale2 | G_zero_overhead | 10.230 | 162.727 | 162.727 | +3.826% |  |
| 10000/1s | scale5 | A_none | 19.144 | 185.089 | 185.089 | +0.000% |  |
| 10000/1s | scale5 | B_ungated | 17.525 | 180.468 | 181.988 | +1.511% |  |
| 10000/1s | scale5 | C_reserve | 17.525 | 180.468 | 181.988 | +1.511% |  |
| 10000/1s | scale5 | D_jev_own | 17.715 | 181.043 | 182.817 | +1.049% |  |
| 10000/1s | scale5 | D_jev_all | 17.715 | 181.043 | 182.817 | +1.049% |  |
| 10000/1s | scale5 | E_post | 17.376 | 180.468 | 180.468 | +2.373% | False |
| 10000/1s | scale5 | E_pipeline | 17.376 | 180.468 | 180.468 | +2.373% | False |
| 10000/1s | scale5 | F_full_generation | 15.644 | 177.153 | 177.153 | +4.299% |  |
| 10000/1s | scale5 | G_zero_overhead | 13.959 | 172.044 | 172.044 | +7.292% |  |
| 10000/1s | scale10 | A_none | 29.895 | 234.039 | 234.039 | +0.000% |  |
| 10000/1s | scale10 | B_ungated | 26.380 | 211.729 | 213.083 | +9.849% |  |
| 10000/1s | scale10 | C_reserve | 26.380 | 211.729 | 213.083 | +9.849% |  |
| 10000/1s | scale10 | D_jev_own | 26.915 | 214.792 | 216.314 | +8.183% |  |
| 10000/1s | scale10 | D_jev_all | 26.915 | 214.792 | 216.314 | +8.183% |  |
| 10000/1s | scale10 | E_post | 26.111 | 211.729 | 211.729 | +10.538% | False |
| 10000/1s | scale10 | E_pipeline | 26.111 | 211.729 | 211.729 | +10.538% | False |
| 10000/1s | scale10 | F_full_generation | 22.025 | 193.908 | 193.908 | +21.606% |  |
| 10000/1s | scale10 | G_zero_overhead | 20.320 | 188.869 | 188.869 | +24.699% |  |
| 10000/1s | fixed1 | A_none | 11.427 | 166.212 | 166.212 | +0.000% |  |
| 10000/1s | fixed1 | B_ungated | 11.163 | 165.778 | 165.789 | +0.241% |  |
| 10000/1s | fixed1 | C_reserve | 11.163 | 165.778 | 165.789 | +0.241% |  |
| 10000/1s | fixed1 | D_jev_own | 11.360 | 166.192 | 166.204 | +0.004% |  |
| 10000/1s | fixed1 | D_jev_all | 11.360 | 166.192 | 166.204 | +0.004% |  |
| 10000/1s | fixed1 | E_post | 11.163 | 165.778 | 165.789 | +0.241% | False |
| 10000/1s | fixed1 | E_pipeline | 11.163 | 165.778 | 165.778 | +0.248% | False |
| 10000/1s | fixed1 | F_full_generation | 11.110 | 164.637 | 164.649 | +0.933% |  |
| 10000/1s | fixed1 | G_zero_overhead | 9.564 | 160.914 | 160.914 | +3.224% |  |
| 10000/1s | fixed2 | A_none | 14.460 | 174.076 | 174.076 | +0.000% |  |
| 10000/1s | fixed2 | B_ungated | 13.505 | 171.873 | 172.885 | +0.637% |  |
| 10000/1s | fixed2 | C_reserve | 13.505 | 171.873 | 172.885 | +0.637% |  |
| 10000/1s | fixed2 | D_jev_own | 13.707 | 172.434 | 173.699 | +0.163% |  |
| 10000/1s | fixed2 | D_jev_all | 13.707 | 172.434 | 173.699 | +0.163% |  |
| 10000/1s | fixed2 | E_post | 13.497 | 171.873 | 171.873 | +1.232% | False |
| 10000/1s | fixed2 | E_pipeline | 13.497 | 171.873 | 171.873 | +1.232% | False |
| 10000/1s | fixed2 | F_full_generation | 12.937 | 169.093 | 169.093 | +2.872% |  |
| 10000/1s | fixed2 | G_zero_overhead | 11.283 | 165.450 | 165.450 | +5.077% |  |
| 10000/1s | fixed5 | A_none | 23.560 | 201.292 | 201.292 | +0.000% |  |
| 10000/1s | fixed5 | B_ungated | 20.605 | 189.873 | 190.885 | +5.643% |  |
| 10000/1s | fixed5 | C_reserve | 20.605 | 189.873 | 190.885 | +5.643% |  |
| 10000/1s | fixed5 | D_jev_own | 20.953 | 190.425 | 191.690 | +5.193% |  |
| 10000/1s | fixed5 | D_jev_all | 20.953 | 190.425 | 191.690 | +5.193% |  |
| 10000/1s | fixed5 | E_post | 20.597 | 189.873 | 189.873 | +6.213% | False |
| 10000/1s | fixed5 | E_pipeline | 20.597 | 189.873 | 189.873 | +6.213% | False |
| 10000/1s | fixed5 | F_full_generation | 18.337 | 182.162 | 182.162 | +10.582% |  |
| 10000/1s | fixed5 | G_zero_overhead | 16.553 | 178.929 | 178.929 | +12.510% |  |
| 10000/1s | fixed10 | A_none | 38.727 | 308.049 | 308.049 | +0.000% |  |
| 10000/1s | fixed10 | B_ungated | 32.438 | 255.547 | 255.547 | +20.588% |  |
| 10000/1s | fixed10 | C_reserve | 32.438 | 255.547 | 255.547 | +20.588% |  |
| 10000/1s | fixed10 | D_jev_own | 33.012 | 258.214 | 258.742 | +19.063% |  |
| 10000/1s | fixed10 | D_jev_all | 33.012 | 258.214 | 258.742 | +19.063% |  |
| 10000/1s | fixed10 | E_post | 32.430 | 255.464 | 255.464 | +20.628% | False |
| 10000/1s | fixed10 | E_pipeline | 32.430 | 255.464 | 255.464 | +20.628% | False |
| 10000/1s | fixed10 | F_full_generation | 27.337 | 216.646 | 216.767 | +42.119% |  |
| 10000/1s | fixed10 | G_zero_overhead | 25.387 | 208.233 | 208.233 | +48.209% |  |
| 12/30s | native | A_none | 28.185 | 215.933 | 215.933 | +0.000% |  |
| 12/30s | native | B_ungated | 31.454 | 245.026 | 245.026 | -11.876% |  |
| 12/30s | native | C_reserve | 28.185 | 215.933 | 215.933 | +0.000% |  |
| 12/30s | native | D_jev_own | 28.542 | 216.690 | 216.690 | -0.346% |  |
| 12/30s | native | D_jev_all | 28.211 | 216.490 | 216.617 | -0.313% |  |
| 12/30s | native | E_post | 27.872 | 215.026 | 215.026 | +0.419% | True |
| 12/30s | native | E_pipeline | 27.872 | 215.026 | 215.026 | +0.419% | True |
| 12/30s | native | F_full_generation | 28.174 | 216.032 | 216.032 | -0.044% |  |
| 12/30s | native | G_zero_overhead | 27.130 | 213.767 | 213.767 | +1.013% |  |
| 12/30s | scale2 | A_none | 28.214 | 218.967 | 218.967 | +0.000% |  |
| 12/30s | scale2 | B_ungated | 40.705 | 325.684 | 326.342 | -32.832% |  |
| 12/30s | scale2 | C_reserve | 28.214 | 218.967 | 218.967 | +0.000% |  |
| 12/30s | scale2 | D_jev_own | 31.832 | 248.967 | 248.967 | -12.051% |  |
| 12/30s | scale2 | D_jev_all | 28.489 | 218.967 | 218.967 | +0.000% |  |
| 12/30s | scale2 | E_post | 28.090 | 217.277 | 217.277 | +0.771% | False |
| 12/30s | scale2 | E_pipeline | 28.090 | 217.277 | 217.277 | +0.771% | False |
| 12/30s | scale2 | F_full_generation | 28.348 | 217.117 | 217.275 | +0.779% |  |
| 12/30s | scale2 | G_zero_overhead | 27.599 | 215.717 | 215.717 | +1.509% |  |
| 12/30s | scale5 | A_none | 29.099 | 226.658 | 226.658 | +0.000% |  |
| 12/30s | scale5 | B_ungated | 48.243 | 383.339 | 383.339 | -40.798% |  |
| 12/30s | scale5 | C_reserve | 29.099 | 226.658 | 226.658 | +0.000% |  |
| 12/30s | scale5 | D_jev_own | 39.883 | 314.755 | 314.755 | -27.994% |  |
| 12/30s | scale5 | D_jev_all | 29.925 | 233.747 | 233.747 | -2.825% |  |
| 12/30s | scale5 | E_post | 28.434 | 221.252 | 221.252 | +2.447% | False |
| 12/30s | scale5 | E_pipeline | 28.434 | 221.252 | 221.252 | +2.447% | False |
| 12/30s | scale5 | F_full_generation | 28.521 | 221.783 | 221.783 | +2.197% |  |
| 12/30s | scale5 | G_zero_overhead | 28.320 | 218.971 | 218.971 | +3.514% |  |
| 12/30s | scale10 | A_none | 31.508 | 245.391 | 245.391 | +0.000% |  |
| 12/30s | scale10 | B_ungated | 50.464 | 404.169 | 404.169 | -39.209% |  |
| 12/30s | scale10 | C_reserve | 31.508 | 245.391 | 245.391 | +0.000% |  |
| 12/30s | scale10 | D_jev_own | 47.748 | 380.847 | 380.847 | -35.582% |  |
| 12/30s | scale10 | D_jev_all | 38.532 | 306.408 | 306.408 | -19.923% |  |
| 12/30s | scale10 | E_post | 29.655 | 232.823 | 232.823 | +5.395% | False |
| 12/30s | scale10 | E_pipeline | 29.655 | 232.823 | 232.823 | +5.395% | False |
| 12/30s | scale10 | F_full_generation | 29.151 | 227.673 | 227.673 | +7.823% |  |
| 12/30s | scale10 | G_zero_overhead | 29.090 | 226.246 | 226.246 | +8.481% |  |
| 12/30s | fixed1 | A_none | 28.499 | 215.798 | 215.798 | +0.000% |  |
| 12/30s | fixed1 | B_ungated | 35.414 | 274.878 | 274.957 | -21.514% |  |
| 12/30s | fixed1 | C_reserve | 28.499 | 215.798 | 215.798 | +0.000% |  |
| 12/30s | fixed1 | D_jev_own | 28.608 | 217.688 | 217.719 | -0.871% |  |
| 12/30s | fixed1 | D_jev_all | 28.286 | 216.294 | 216.329 | -0.243% |  |
| 12/30s | fixed1 | E_post | 28.256 | 215.798 | 215.837 | -0.018% | False |
| 12/30s | fixed1 | E_pipeline | 28.256 | 215.798 | 215.798 | +0.000% | False |
| 12/30s | fixed1 | F_full_generation | 28.491 | 215.620 | 215.651 | +0.067% |  |
| 12/30s | fixed1 | G_zero_overhead | 27.819 | 214.691 | 214.691 | +0.514% |  |
| 12/30s | fixed2 | A_none | 28.588 | 219.932 | 219.932 | +0.000% |  |
| 12/30s | fixed2 | B_ungated | 45.938 | 364.303 | 364.715 | -39.698% |  |
| 12/30s | fixed2 | C_reserve | 28.588 | 219.932 | 219.932 | +0.000% |  |
| 12/30s | fixed2 | D_jev_own | 38.178 | 298.598 | 298.598 | -26.188% |  |
| 12/30s | fixed2 | D_jev_all | 28.864 | 219.725 | 220.214 | -0.130% |  |
| 12/30s | fixed2 | E_post | 28.507 | 218.528 | 218.528 | +0.646% | False |
| 12/30s | fixed2 | E_pipeline | 28.507 | 218.528 | 218.528 | +0.646% | False |
| 12/30s | fixed2 | F_full_generation | 28.220 | 218.308 | 218.430 | +0.686% |  |
| 12/30s | fixed2 | G_zero_overhead | 28.017 | 216.323 | 216.323 | +1.666% |  |
| 12/30s | fixed5 | A_none | 29.549 | 229.131 | 229.131 | +0.000% |  |
| 12/30s | fixed5 | B_ungated | 47.149 | 371.337 | 371.337 | -38.324% |  |
| 12/30s | fixed5 | C_reserve | 29.549 | 229.131 | 229.131 | +0.000% |  |
| 12/30s | fixed5 | D_jev_own | 44.588 | 345.201 | 345.668 | -33.743% |  |
| 12/30s | fixed5 | D_jev_all | 31.754 | 249.800 | 250.308 | -8.449% |  |
| 12/30s | fixed5 | E_post | 29.169 | 226.480 | 226.480 | +1.142% | False |
| 12/30s | fixed5 | E_pipeline | 29.169 | 226.480 | 226.480 | +1.142% | False |
| 12/30s | fixed5 | F_full_generation | 28.886 | 224.308 | 224.430 | +2.046% |  |
| 12/30s | fixed5 | G_zero_overhead | 28.617 | 222.323 | 222.323 | +3.013% |  |
| 12/30s | fixed10 | A_none | 38.727 | 308.049 | 308.049 | +0.000% |  |
| 12/30s | fixed10 | B_ungated | 48.984 | 393.211 | 393.211 | -21.459% |  |
| 12/30s | fixed10 | C_reserve | 37.853 | 298.581 | 298.581 | +3.252% |  |
| 12/30s | fixed10 | D_jev_own | 47.563 | 376.421 | 376.434 | -18.103% |  |
| 12/30s | fixed10 | D_jev_all | 41.860 | 326.174 | 326.791 | -5.674% |  |
| 12/30s | fixed10 | E_post | 33.498 | 262.487 | 262.487 | +17.428% | False |
| 12/30s | fixed10 | E_pipeline | 33.498 | 262.487 | 262.487 | +17.428% | False |
| 12/30s | fixed10 | F_full_generation | 30.200 | 234.926 | 234.926 | +31.084% |  |
| 12/30s | fixed10 | G_zero_overhead | 29.810 | 228.808 | 228.808 | +34.643% |  |
| 6/60s | native | A_none | 112.990 | 902.635 | 902.635 | +0.000% |  |
| 6/60s | native | B_ungated | 116.348 | 905.033 | 905.033 | -0.265% |  |
| 6/60s | native | C_reserve | 112.990 | 902.635 | 902.635 | +0.000% |  |
| 6/60s | native | D_jev_own | 112.990 | 902.635 | 902.810 | -0.019% |  |
| 6/60s | native | D_jev_all | 112.990 | 902.635 | 902.810 | -0.019% |  |
| 6/60s | native | E_post | 112.341 | 883.166 | 883.341 | +2.283% | True |
| 6/60s | native | E_pipeline | 112.341 | 883.166 | 883.166 | +2.302% | True |
| 6/60s | native | F_full_generation | 113.637 | 902.879 | 902.879 | -0.027% |  |
| 6/60s | native | G_zero_overhead | 112.307 | 883.329 | 883.329 | +2.285% |  |
| 6/60s | scale2 | A_none | 113.185 | 904.209 | 904.209 | +0.000% |  |
| 6/60s | scale2 | B_ungated | 137.163 | 1086.376 | 1086.376 | -16.768% |  |
| 6/60s | scale2 | C_reserve | 113.185 | 904.209 | 904.209 | +0.000% |  |
| 6/60s | scale2 | D_jev_own | 119.940 | 947.097 | 947.097 | -4.450% |  |
| 6/60s | scale2 | D_jev_all | 113.183 | 904.209 | 904.209 | +0.000% |  |
| 6/60s | scale2 | E_post | 111.875 | 884.479 | 884.479 | +2.324% | False |
| 6/60s | scale2 | E_pipeline | 111.875 | 884.479 | 884.479 | +2.324% | False |
| 6/60s | scale2 | F_full_generation | 110.563 | 847.117 | 847.275 | +6.720% |  |
| 6/60s | scale2 | G_zero_overhead | 112.437 | 884.900 | 884.900 | +2.278% |  |
| 6/60s | scale5 | A_none | 113.644 | 906.168 | 906.168 | +0.000% |  |
| 6/60s | scale5 | B_ungated | 152.828 | 1208.940 | 1208.940 | -25.045% |  |
| 6/60s | scale5 | C_reserve | 113.644 | 906.168 | 906.168 | +0.000% |  |
| 6/60s | scale5 | D_jev_own | 141.161 | 1112.878 | 1112.878 | -18.516% |  |
| 6/60s | scale5 | D_jev_all | 114.914 | 906.923 | 908.042 | -0.207% |  |
| 6/60s | scale5 | E_post | 109.751 | 854.755 | 854.755 | +6.015% | False |
| 6/60s | scale5 | E_pipeline | 109.751 | 854.755 | 854.755 | +6.015% | False |
| 6/60s | scale5 | F_full_generation | 109.743 | 852.969 | 852.969 | +6.238% |  |
| 6/60s | scale5 | G_zero_overhead | 112.217 | 871.748 | 871.748 | +4.037% |  |
| 6/60s | scale10 | A_none | 114.436 | 910.829 | 910.829 | +0.000% |  |
| 6/60s | scale10 | B_ungated | 153.615 | 1216.033 | 1216.033 | -25.101% |  |
| 6/60s | scale10 | C_reserve | 114.436 | 910.829 | 910.829 | +0.000% |  |
| 6/60s | scale10 | D_jev_own | 147.747 | 1161.544 | 1161.544 | -21.586% |  |
| 6/60s | scale10 | D_jev_all | 115.269 | 916.280 | 916.280 | -0.593% |  |
| 6/60s | scale10 | E_post | 110.571 | 866.982 | 866.982 | +5.056% | False |
| 6/60s | scale10 | E_pipeline | 110.571 | 866.982 | 866.982 | +5.056% | False |
| 6/60s | scale10 | F_full_generation | 110.537 | 862.232 | 862.232 | +5.637% |  |
| 6/60s | scale10 | G_zero_overhead | 112.951 | 897.475 | 897.475 | +1.554% |  |
| 6/60s | fixed1 | A_none | 113.022 | 902.184 | 902.184 | +0.000% |  |
| 6/60s | fixed1 | B_ungated | 127.020 | 1003.148 | 1003.227 | -10.004% |  |
| 6/60s | fixed1 | C_reserve | 113.022 | 902.184 | 902.184 | +0.000% |  |
| 6/60s | fixed1 | D_jev_own | 113.728 | 903.363 | 903.451 | -0.140% |  |
| 6/60s | fixed1 | D_jev_all | 113.022 | 902.184 | 902.203 | -0.002% |  |
| 6/60s | fixed1 | E_post | 111.087 | 864.675 | 864.715 | +4.428% | False |
| 6/60s | fixed1 | E_pipeline | 111.087 | 864.675 | 864.675 | +4.433% | False |
| 6/60s | fixed1 | F_full_generation | 111.705 | 882.576 | 882.698 | +2.307% |  |
| 6/60s | fixed1 | G_zero_overhead | 111.700 | 883.922 | 883.922 | +2.162% |  |
| 6/60s | fixed2 | A_none | 113.210 | 903.184 | 903.184 | +0.000% |  |
| 6/60s | fixed2 | B_ungated | 149.937 | 1184.946 | 1184.946 | -23.737% |  |
| 6/60s | fixed2 | C_reserve | 113.210 | 903.184 | 903.184 | +0.000% |  |
| 6/60s | fixed2 | D_jev_own | 139.206 | 1084.898 | 1084.911 | -16.750% |  |
| 6/60s | fixed2 | D_jev_all | 113.848 | 903.198 | 903.211 | -0.003% |  |
| 6/60s | fixed2 | E_post | 109.327 | 847.211 | 847.211 | +6.607% | False |
| 6/60s | fixed2 | E_pipeline | 109.327 | 847.211 | 847.211 | +6.607% | False |
| 6/60s | fixed2 | F_full_generation | 109.329 | 848.193 | 848.193 | +6.484% |  |
| 6/60s | fixed2 | G_zero_overhead | 111.844 | 885.256 | 885.256 | +2.118% |  |
| 6/60s | fixed5 | A_none | 113.777 | 906.184 | 906.184 | +0.000% |  |
| 6/60s | fixed5 | B_ungated | 153.005 | 1207.856 | 1207.856 | -24.976% |  |
| 6/60s | fixed5 | C_reserve | 113.777 | 906.184 | 906.184 | +0.000% |  |
| 6/60s | fixed5 | D_jev_own | 141.806 | 1113.072 | 1113.072 | -18.536% |  |
| 6/60s | fixed5 | D_jev_all | 115.655 | 908.481 | 908.494 | -0.253% |  |
| 6/60s | fixed5 | E_post | 109.957 | 855.109 | 855.109 | +5.974% | False |
| 6/60s | fixed5 | E_pipeline | 109.957 | 855.109 | 855.109 | +5.974% | False |
| 6/60s | fixed5 | F_full_generation | 109.800 | 853.333 | 853.333 | +6.195% |  |
| 6/60s | fixed5 | G_zero_overhead | 112.278 | 889.256 | 889.256 | +1.986% |  |
| 6/60s | fixed10 | A_none | 114.722 | 911.184 | 911.184 | +0.000% |  |
| 6/60s | fixed10 | B_ungated | 153.783 | 1214.523 | 1214.523 | -24.975% |  |
| 6/60s | fixed10 | C_reserve | 114.722 | 911.184 | 911.184 | +0.000% |  |
| 6/60s | fixed10 | D_jev_own | 144.815 | 1142.707 | 1143.198 | -20.270% |  |
| 6/60s | fixed10 | D_jev_all | 116.365 | 911.563 | 912.090 | -0.099% |  |
| 6/60s | fixed10 | E_post | 110.957 | 866.776 | 866.776 | +5.127% | False |
| 6/60s | fixed10 | E_pipeline | 110.957 | 866.776 | 866.776 | +5.127% | False |
| 6/60s | fixed10 | F_full_generation | 110.578 | 861.666 | 861.666 | +5.751% |  |
| 6/60s | fixed10 | G_zero_overhead | 113.000 | 895.922 | 895.922 | +1.769% |  |

## Worker release and retention: native and synthetic 10×

| Duration | Quota | Workers | Release | Retention | Policy | Mean answer s | All answers s | All work s | Throughput gain |
|---|---|---:|---|---|---|---:|---:|---:|---:|
| native | 10000/1s | 1 | drain | original | A_none | 10.543 | 316.305 | 316.305 | +0.000% |
| native | 10000/1s | 1 | drain | original | B_ungated | 10.399 | 321.343 | 321.698 | -1.676% |
| native | 10000/1s | 1 | drain | original | D_jev_all | 10.495 | 325.086 | 325.440 | -2.807% |
| native | 10000/1s | 1 | drain | original | E_pipeline | 10.399 | 311.973 | 311.973 | +1.388% |
| native | 10000/1s | 1 | drain | original | F_perfect_predictor | 10.371 | 311.682 | 311.682 | +1.483% |
| native | 10000/1s | 1 | drain | one extra action + dedup | A_none | 10.543 | 316.305 | 316.305 | +0.000% |
| native | 10000/1s | 1 | drain | one extra action + dedup | B_ungated | 10.372 | 320.601 | 320.955 | -1.449% |
| native | 10000/1s | 1 | drain | one extra action + dedup | D_jev_all | 10.413 | 322.512 | 322.866 | -2.032% |
| native | 10000/1s | 1 | drain | one extra action + dedup | E_pipeline | 10.372 | 311.156 | 311.156 | +1.655% |
| native | 10000/1s | 1 | drain | one extra action + dedup | F_perfect_predictor | 10.371 | 311.682 | 311.682 | +1.483% |
| native | 10000/1s | 1 | answer | original | A_none | 10.543 | 316.305 | 316.305 | +0.000% |
| native | 10000/1s | 1 | answer | original | B_ungated | 10.399 | 311.973 | 312.328 | +1.273% |
| native | 10000/1s | 1 | answer | original | D_jev_all | 10.495 | 314.851 | 315.205 | +0.349% |
| native | 10000/1s | 1 | answer | original | E_pipeline | 10.399 | 311.973 | 311.973 | +1.388% |
| native | 10000/1s | 1 | answer | original | F_perfect_predictor | 10.371 | 311.119 | 311.119 | +1.667% |
| native | 10000/1s | 1 | answer | one extra action + dedup | A_none | 10.543 | 316.305 | 316.305 | +0.000% |
| native | 10000/1s | 1 | answer | one extra action + dedup | B_ungated | 10.372 | 311.156 | 311.510 | +1.539% |
| native | 10000/1s | 1 | answer | one extra action + dedup | D_jev_all | 10.413 | 312.404 | 312.758 | +1.134% |
| native | 10000/1s | 1 | answer | one extra action + dedup | E_pipeline | 10.372 | 311.156 | 311.156 | +1.655% |
| native | 10000/1s | 1 | answer | one extra action + dedup | F_perfect_predictor | 10.371 | 311.119 | 311.119 | +1.667% |
| native | 10000/1s | 2 | drain | original | A_none | 10.543 | 174.957 | 174.957 | +0.000% |
| native | 10000/1s | 2 | drain | original | B_ungated | 10.399 | 175.386 | 175.770 | -0.456% |
| native | 10000/1s | 2 | drain | original | D_jev_all | 10.488 | 177.301 | 177.732 | -1.616% |
| native | 10000/1s | 2 | drain | original | E_pipeline | 10.399 | 173.771 | 173.771 | +0.628% |
| native | 10000/1s | 2 | drain | original | F_perfect_predictor | 10.371 | 173.735 | 173.735 | +0.680% |
| native | 10000/1s | 2 | drain | one extra action + dedup | A_none | 10.543 | 174.957 | 174.957 | +0.000% |
| native | 10000/1s | 2 | drain | one extra action + dedup | B_ungated | 10.372 | 175.281 | 175.711 | -0.417% |
| native | 10000/1s | 2 | drain | one extra action + dedup | D_jev_all | 10.407 | 176.163 | 176.593 | -0.926% |
| native | 10000/1s | 2 | drain | one extra action + dedup | E_pipeline | 10.372 | 173.596 | 173.596 | +0.740% |
| native | 10000/1s | 2 | drain | one extra action + dedup | F_perfect_predictor | 10.371 | 173.735 | 173.735 | +0.680% |
| native | 10000/1s | 2 | answer | original | A_none | 10.543 | 174.957 | 174.957 | +0.000% |
| native | 10000/1s | 2 | answer | original | B_ungated | 10.399 | 173.771 | 174.155 | +0.405% |
| native | 10000/1s | 2 | answer | original | D_jev_all | 10.488 | 174.957 | 175.341 | -0.220% |
| native | 10000/1s | 2 | answer | original | E_pipeline | 10.399 | 173.771 | 173.771 | +0.628% |
| native | 10000/1s | 2 | answer | original | F_perfect_predictor | 10.371 | 173.735 | 173.735 | +0.680% |
| native | 10000/1s | 2 | answer | one extra action + dedup | A_none | 10.543 | 174.957 | 174.957 | +0.000% |
| native | 10000/1s | 2 | answer | one extra action + dedup | B_ungated | 10.372 | 173.596 | 173.979 | +0.517% |
| native | 10000/1s | 2 | answer | one extra action + dedup | D_jev_all | 10.407 | 174.068 | 174.451 | +0.266% |
| native | 10000/1s | 2 | answer | one extra action + dedup | E_pipeline | 10.372 | 173.596 | 173.596 | +0.740% |
| native | 10000/1s | 2 | answer | one extra action + dedup | F_perfect_predictor | 10.371 | 173.735 | 173.735 | +0.680% |
| native | 10000/1s | 4 | drain | original | A_none | 10.543 | 163.647 | 163.647 | +0.000% |
| native | 10000/1s | 4 | drain | original | B_ungated | 10.399 | 163.828 | 164.211 | -0.340% |
| native | 10000/1s | 4 | drain | original | D_jev_all | 10.500 | 164.490 | 164.874 | -0.720% |
| native | 10000/1s | 4 | drain | original | E_pipeline | 10.399 | 163.283 | 163.283 | +0.212% |
| native | 10000/1s | 4 | drain | original | F_perfect_predictor | 10.371 | 162.580 | 162.580 | +0.645% |
| native | 10000/1s | 4 | drain | one extra action + dedup | A_none | 10.543 | 163.647 | 163.647 | +0.000% |
| native | 10000/1s | 4 | drain | one extra action + dedup | B_ungated | 10.372 | 163.828 | 164.211 | -0.340% |
| native | 10000/1s | 4 | drain | one extra action + dedup | D_jev_all | 10.416 | 164.224 | 164.607 | -0.567% |
| native | 10000/1s | 4 | drain | one extra action + dedup | E_pipeline | 10.372 | 163.283 | 163.283 | +0.212% |
| native | 10000/1s | 4 | drain | one extra action + dedup | F_perfect_predictor | 10.371 | 162.580 | 162.580 | +0.645% |
| native | 10000/1s | 4 | answer | original | A_none | 10.543 | 163.647 | 163.647 | +0.000% |
| native | 10000/1s | 4 | answer | original | B_ungated | 10.399 | 163.283 | 163.666 | -0.023% |
| native | 10000/1s | 4 | answer | original | D_jev_all | 10.510 | 163.647 | 164.030 | -0.234% |
| native | 10000/1s | 4 | answer | original | E_pipeline | 10.399 | 163.283 | 163.283 | +0.212% |
| native | 10000/1s | 4 | answer | original | F_perfect_predictor | 10.371 | 162.580 | 162.580 | +0.645% |
| native | 10000/1s | 4 | answer | one extra action + dedup | A_none | 10.543 | 163.647 | 163.647 | +0.000% |
| native | 10000/1s | 4 | answer | one extra action + dedup | B_ungated | 10.372 | 163.283 | 163.666 | -0.023% |
| native | 10000/1s | 4 | answer | one extra action + dedup | D_jev_all | 10.416 | 163.283 | 163.666 | -0.023% |
| native | 10000/1s | 4 | answer | one extra action + dedup | E_pipeline | 10.372 | 163.283 | 163.283 | +0.212% |
| native | 10000/1s | 4 | answer | one extra action + dedup | F_perfect_predictor | 10.371 | 162.580 | 162.580 | +0.645% |
| native | 10000/1s | 8 | drain | original | A_none | 10.543 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | drain | original | B_ungated | 10.399 | 158.190 | 158.574 | -0.509% |
| native | 10000/1s | 8 | drain | original | D_jev_all | 10.513 | 158.190 | 158.574 | -0.509% |
| native | 10000/1s | 8 | drain | original | E_pipeline | 10.399 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | drain | original | F_perfect_predictor | 10.371 | 157.097 | 157.097 | +0.422% |
| native | 10000/1s | 8 | drain | one extra action + dedup | A_none | 10.543 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | drain | one extra action + dedup | B_ungated | 10.372 | 158.147 | 158.530 | -0.482% |
| native | 10000/1s | 8 | drain | one extra action + dedup | D_jev_all | 10.433 | 158.190 | 158.574 | -0.509% |
| native | 10000/1s | 8 | drain | one extra action + dedup | E_pipeline | 10.372 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | drain | one extra action + dedup | F_perfect_predictor | 10.371 | 157.097 | 157.097 | +0.422% |
| native | 10000/1s | 8 | answer | original | A_none | 10.543 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | answer | original | B_ungated | 10.399 | 157.760 | 158.143 | -0.242% |
| native | 10000/1s | 8 | answer | original | D_jev_all | 10.522 | 157.760 | 158.143 | -0.242% |
| native | 10000/1s | 8 | answer | original | E_pipeline | 10.399 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | answer | original | F_perfect_predictor | 10.371 | 157.097 | 157.097 | +0.422% |
| native | 10000/1s | 8 | answer | one extra action + dedup | A_none | 10.543 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | answer | one extra action + dedup | B_ungated | 10.372 | 157.760 | 158.143 | -0.242% |
| native | 10000/1s | 8 | answer | one extra action + dedup | D_jev_all | 10.428 | 157.760 | 158.143 | -0.242% |
| native | 10000/1s | 8 | answer | one extra action + dedup | E_pipeline | 10.372 | 157.760 | 157.760 | +0.000% |
| native | 10000/1s | 8 | answer | one extra action + dedup | F_perfect_predictor | 10.371 | 157.097 | 157.097 | +0.422% |
| native | 12/30s | 1 | drain | original | A_none | 11.929 | 357.862 | 357.862 | +0.000% |
| native | 12/30s | 1 | drain | original | B_ungated | 13.038 | 400.600 | 400.954 | -10.754% |
| native | 12/30s | 1 | drain | original | D_jev_all | 11.933 | 368.236 | 368.591 | -2.921% |
| native | 12/30s | 1 | drain | original | E_pipeline | 11.895 | 356.851 | 356.851 | +0.289% |
| native | 12/30s | 1 | drain | original | F_perfect_predictor | 11.836 | 355.630 | 355.630 | +0.626% |
| native | 12/30s | 1 | drain | one extra action + dedup | A_none | 11.929 | 357.862 | 357.862 | +0.000% |
| native | 12/30s | 1 | drain | one extra action + dedup | B_ungated | 16.528 | 505.371 | 505.725 | -29.226% |
| native | 12/30s | 1 | drain | one extra action + dedup | D_jev_all | 14.279 | 438.259 | 438.614 | -18.368% |
| native | 12/30s | 1 | drain | one extra action + dedup | E_pipeline | 11.892 | 356.754 | 356.754 | +0.317% |
| native | 12/30s | 1 | drain | one extra action + dedup | F_perfect_predictor | 11.836 | 355.630 | 355.630 | +0.626% |
| native | 12/30s | 1 | answer | original | A_none | 11.929 | 357.862 | 357.862 | +0.000% |
| native | 12/30s | 1 | answer | original | B_ungated | 13.279 | 398.375 | 398.729 | -10.249% |
| native | 12/30s | 1 | answer | original | D_jev_all | 12.153 | 364.600 | 364.955 | -1.963% |
| native | 12/30s | 1 | answer | original | E_pipeline | 11.895 | 356.851 | 356.851 | +0.289% |
| native | 12/30s | 1 | answer | original | F_perfect_predictor | 11.850 | 355.492 | 355.492 | +0.666% |
| native | 12/30s | 1 | answer | one extra action + dedup | A_none | 11.929 | 357.862 | 357.862 | +0.000% |
| native | 12/30s | 1 | answer | one extra action + dedup | B_ungated | 16.846 | 505.371 | 505.725 | -29.226% |
| native | 12/30s | 1 | answer | one extra action + dedup | D_jev_all | 14.592 | 437.768 | 438.123 | -18.272% |
| native | 12/30s | 1 | answer | one extra action + dedup | E_pipeline | 11.892 | 356.754 | 356.754 | +0.317% |
| native | 12/30s | 1 | answer | one extra action + dedup | F_perfect_predictor | 11.850 | 355.492 | 355.492 | +0.666% |
| native | 12/30s | 2 | drain | original | A_none | 14.560 | 219.646 | 219.646 | +0.000% |
| native | 12/30s | 2 | drain | original | B_ungated | 16.121 | 248.203 | 248.378 | -11.575% |
| native | 12/30s | 2 | drain | original | D_jev_all | 14.328 | 220.813 | 221.295 | -0.749% |
| native | 12/30s | 2 | drain | original | E_pipeline | 14.471 | 217.900 | 217.900 | +0.817% |
| native | 12/30s | 2 | drain | original | F_perfect_predictor | 14.505 | 218.736 | 218.736 | +0.423% |
| native | 12/30s | 2 | drain | one extra action + dedup | A_none | 14.560 | 219.646 | 219.646 | +0.000% |
| native | 12/30s | 2 | drain | one extra action + dedup | B_ungated | 23.350 | 356.353 | 356.707 | -38.339% |
| native | 12/30s | 2 | drain | one extra action + dedup | D_jev_all | 16.477 | 257.506 | 257.681 | -14.593% |
| native | 12/30s | 2 | drain | one extra action + dedup | E_pipeline | 14.468 | 217.900 | 217.900 | +0.817% |
| native | 12/30s | 2 | drain | one extra action + dedup | F_perfect_predictor | 14.505 | 218.736 | 218.736 | +0.423% |
| native | 12/30s | 2 | answer | original | A_none | 14.560 | 219.646 | 219.646 | +0.000% |
| native | 12/30s | 2 | answer | original | B_ungated | 16.409 | 247.873 | 248.049 | -11.459% |
| native | 12/30s | 2 | answer | original | D_jev_all | 14.613 | 219.988 | 220.471 | -0.376% |
| native | 12/30s | 2 | answer | original | E_pipeline | 14.471 | 217.900 | 217.900 | +0.817% |
| native | 12/30s | 2 | answer | original | F_perfect_predictor | 14.520 | 218.598 | 218.598 | +0.488% |
| native | 12/30s | 2 | answer | one extra action + dedup | A_none | 14.560 | 219.646 | 219.646 | +0.000% |
| native | 12/30s | 2 | answer | one extra action + dedup | B_ungated | 23.629 | 355.948 | 356.303 | -38.261% |
| native | 12/30s | 2 | answer | one extra action + dedup | D_jev_all | 16.840 | 258.020 | 258.195 | -14.774% |
| native | 12/30s | 2 | answer | one extra action + dedup | E_pipeline | 14.468 | 217.900 | 217.900 | +0.817% |
| native | 12/30s | 2 | answer | one extra action + dedup | F_perfect_predictor | 14.520 | 218.598 | 218.598 | +0.488% |
| native | 12/30s | 4 | drain | original | A_none | 28.185 | 215.933 | 215.933 | +0.000% |
| native | 12/30s | 4 | drain | original | B_ungated | 31.281 | 246.261 | 246.437 | -12.374% |
| native | 12/30s | 4 | drain | original | D_jev_all | 27.863 | 215.476 | 215.476 | +0.211% |
| native | 12/30s | 4 | drain | original | E_pipeline | 27.872 | 215.026 | 215.026 | +0.419% |
| native | 12/30s | 4 | drain | original | F_perfect_predictor | 28.162 | 216.032 | 216.032 | -0.044% |
| native | 12/30s | 4 | drain | one extra action + dedup | A_none | 28.185 | 215.933 | 215.933 | +0.000% |
| native | 12/30s | 4 | drain | one extra action + dedup | B_ungated | 40.860 | 325.685 | 325.685 | -33.597% |
| native | 12/30s | 4 | drain | one extra action + dedup | D_jev_all | 27.918 | 216.690 | 216.690 | -0.346% |
| native | 12/30s | 4 | drain | one extra action + dedup | E_pipeline | 27.872 | 215.026 | 215.026 | +0.419% |
| native | 12/30s | 4 | drain | one extra action + dedup | F_perfect_predictor | 28.162 | 216.032 | 216.032 | -0.044% |
| native | 12/30s | 4 | answer | original | A_none | 28.185 | 215.933 | 215.933 | +0.000% |
| native | 12/30s | 4 | answer | original | B_ungated | 31.454 | 245.026 | 245.026 | -11.876% |
| native | 12/30s | 4 | answer | original | D_jev_all | 28.211 | 216.490 | 216.617 | -0.313% |
| native | 12/30s | 4 | answer | original | E_pipeline | 27.872 | 215.026 | 215.026 | +0.419% |
| native | 12/30s | 4 | answer | original | F_perfect_predictor | 28.174 | 216.032 | 216.032 | -0.044% |
| native | 12/30s | 4 | answer | one extra action + dedup | A_none | 28.185 | 215.933 | 215.933 | +0.000% |
| native | 12/30s | 4 | answer | one extra action + dedup | B_ungated | 41.140 | 325.685 | 325.685 | -33.597% |
| native | 12/30s | 4 | answer | one extra action + dedup | D_jev_all | 28.211 | 216.490 | 216.617 | -0.313% |
| native | 12/30s | 4 | answer | one extra action + dedup | E_pipeline | 27.872 | 215.026 | 215.026 | +0.419% |
| native | 12/30s | 4 | answer | one extra action + dedup | F_perfect_predictor | 28.174 | 216.032 | 216.032 | -0.044% |
| native | 12/30s | 8 | drain | original | A_none | 51.762 | 215.753 | 215.753 | +0.000% |
| native | 12/30s | 8 | drain | original | B_ungated | 56.332 | 243.015 | 243.015 | -11.219% |
| native | 12/30s | 8 | drain | original | D_jev_all | 51.439 | 215.753 | 215.753 | +0.000% |
| native | 12/30s | 8 | drain | original | E_pipeline | 52.050 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | drain | original | F_perfect_predictor | 52.018 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | drain | one extra action + dedup | A_none | 51.762 | 215.753 | 215.753 | +0.000% |
| native | 12/30s | 8 | drain | one extra action + dedup | B_ungated | 57.382 | 253.996 | 253.996 | -14.826% |
| native | 12/30s | 8 | drain | one extra action + dedup | D_jev_all | 52.462 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | drain | one extra action + dedup | E_pipeline | 52.034 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | drain | one extra action + dedup | F_perfect_predictor | 52.018 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | answer | original | A_none | 51.762 | 215.753 | 215.753 | +0.000% |
| native | 12/30s | 8 | answer | original | B_ungated | 54.734 | 233.689 | 233.689 | -7.459% |
| native | 12/30s | 8 | answer | original | D_jev_all | 51.762 | 215.753 | 215.753 | +0.000% |
| native | 12/30s | 8 | answer | original | E_pipeline | 52.050 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | answer | original | F_perfect_predictor | 52.018 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | answer | one extra action + dedup | A_none | 51.762 | 215.753 | 215.753 | +0.000% |
| native | 12/30s | 8 | answer | one extra action + dedup | B_ungated | 57.327 | 244.950 | 244.950 | -11.916% |
| native | 12/30s | 8 | answer | one extra action + dedup | D_jev_all | 51.762 | 215.753 | 215.753 | +0.000% |
| native | 12/30s | 8 | answer | one extra action + dedup | E_pipeline | 52.034 | 215.476 | 215.476 | +0.130% |
| native | 12/30s | 8 | answer | one extra action + dedup | F_perfect_predictor | 52.018 | 215.476 | 215.476 | +0.130% |
| native | 6/60s | 1 | drain | original | A_none | 32.211 | 966.334 | 966.334 | +0.000% |
| native | 6/60s | 1 | drain | original | B_ungated | 35.919 | 1087.223 | 1087.577 | -11.148% |
| native | 6/60s | 1 | drain | original | D_jev_all | 32.479 | 984.600 | 984.955 | -1.817% |
| native | 6/60s | 1 | drain | original | E_pipeline | 32.193 | 965.791 | 965.791 | +0.056% |
| native | 6/60s | 1 | drain | original | F_perfect_predictor | 32.119 | 963.910 | 963.910 | +0.251% |
| native | 6/60s | 1 | drain | one extra action + dedup | A_none | 32.211 | 966.334 | 966.334 | +0.000% |
| native | 6/60s | 1 | drain | one extra action + dedup | B_ungated | 47.151 | 1424.123 | 1424.477 | -32.137% |
| native | 6/60s | 1 | drain | one extra action + dedup | D_jev_all | 35.303 | 1069.154 | 1069.508 | -9.585% |
| native | 6/60s | 1 | drain | one extra action + dedup | E_pipeline | 32.193 | 965.791 | 965.791 | +0.056% |
| native | 6/60s | 1 | drain | one extra action + dedup | F_perfect_predictor | 32.119 | 963.910 | 963.910 | +0.251% |
| native | 6/60s | 1 | answer | original | A_none | 32.211 | 966.334 | 966.334 | +0.000% |
| native | 6/60s | 1 | answer | original | B_ungated | 36.224 | 1086.732 | 1087.086 | -11.108% |
| native | 6/60s | 1 | answer | original | D_jev_all | 32.820 | 984.600 | 984.955 | -1.817% |
| native | 6/60s | 1 | answer | original | E_pipeline | 32.193 | 965.791 | 965.791 | +0.056% |
| native | 6/60s | 1 | answer | original | F_perfect_predictor | 32.130 | 963.910 | 963.910 | +0.251% |
| native | 6/60s | 1 | answer | one extra action + dedup | A_none | 32.211 | 966.334 | 966.334 | +0.000% |
| native | 6/60s | 1 | answer | one extra action + dedup | B_ungated | 47.471 | 1424.123 | 1424.477 | -32.137% |
| native | 6/60s | 1 | answer | one extra action + dedup | D_jev_all | 35.622 | 1068.663 | 1069.017 | -9.540% |
| native | 6/60s | 1 | answer | one extra action + dedup | E_pipeline | 32.193 | 965.791 | 965.791 | +0.056% |
| native | 6/60s | 1 | answer | one extra action + dedup | F_perfect_predictor | 32.130 | 963.910 | 963.910 | +0.251% |
| native | 6/60s | 2 | drain | original | A_none | 58.260 | 901.640 | 901.640 | +0.000% |
| native | 6/60s | 2 | drain | original | B_ungated | 64.627 | 983.883 | 984.058 | -8.303% |
| native | 6/60s | 2 | drain | original | D_jev_all | 57.928 | 901.640 | 901.994 | -0.039% |
| native | 6/60s | 2 | drain | original | E_pipeline | 57.021 | 864.937 | 864.937 | +4.339% |
| native | 6/60s | 2 | drain | original | F_perfect_predictor | 57.631 | 883.616 | 883.616 | +2.133% |
| native | 6/60s | 2 | drain | one extra action + dedup | A_none | 58.260 | 901.640 | 901.640 | +0.000% |
| native | 6/60s | 2 | drain | one extra action + dedup | B_ungated | 81.880 | 1243.911 | 1244.087 | -27.491% |
| native | 6/60s | 2 | drain | one extra action + dedup | D_jev_all | 59.244 | 904.066 | 904.241 | -0.288% |
| native | 6/60s | 2 | drain | one extra action + dedup | E_pipeline | 57.021 | 864.937 | 864.937 | +4.339% |
| native | 6/60s | 2 | drain | one extra action + dedup | F_perfect_predictor | 57.631 | 883.616 | 883.616 | +2.133% |
| native | 6/60s | 2 | answer | original | A_none | 58.260 | 901.640 | 901.640 | +0.000% |
| native | 6/60s | 2 | answer | original | B_ungated | 64.898 | 984.724 | 984.899 | -8.384% |
| native | 6/60s | 2 | answer | original | D_jev_all | 58.260 | 901.640 | 901.994 | -0.039% |
| native | 6/60s | 2 | answer | original | E_pipeline | 57.021 | 864.937 | 864.937 | +4.339% |
| native | 6/60s | 2 | answer | original | F_perfect_predictor | 57.639 | 883.616 | 883.616 | +2.133% |
| native | 6/60s | 2 | answer | one extra action + dedup | A_none | 58.260 | 901.640 | 901.640 | +0.000% |
| native | 6/60s | 2 | answer | one extra action + dedup | B_ungated | 80.854 | 1223.722 | 1223.897 | -26.294% |
| native | 6/60s | 2 | answer | one extra action + dedup | D_jev_all | 58.892 | 901.640 | 901.994 | -0.039% |
| native | 6/60s | 2 | answer | one extra action + dedup | E_pipeline | 57.021 | 864.937 | 864.937 | +4.339% |
| native | 6/60s | 2 | answer | one extra action + dedup | F_perfect_predictor | 57.639 | 883.616 | 883.616 | +2.133% |
| native | 6/60s | 4 | drain | original | A_none | 112.990 | 902.635 | 902.635 | +0.000% |
| native | 6/60s | 4 | drain | original | B_ungated | 118.027 | 904.155 | 904.330 | -0.187% |
| native | 6/60s | 4 | drain | original | D_jev_all | 112.673 | 902.635 | 902.810 | -0.019% |
| native | 6/60s | 4 | drain | original | E_pipeline | 112.341 | 883.166 | 883.166 | +2.302% |
| native | 6/60s | 4 | drain | original | F_perfect_predictor | 113.637 | 902.879 | 902.879 | -0.027% |
| native | 6/60s | 4 | drain | one extra action + dedup | A_none | 112.990 | 902.635 | 902.635 | +0.000% |
| native | 6/60s | 4 | drain | one extra action + dedup | B_ungated | 119.368 | 943.922 | 943.922 | -4.291% |
| native | 6/60s | 4 | drain | one extra action + dedup | D_jev_all | 113.325 | 902.635 | 902.810 | -0.019% |
| native | 6/60s | 4 | drain | one extra action + dedup | E_pipeline | 112.341 | 883.166 | 883.166 | +2.302% |
| native | 6/60s | 4 | drain | one extra action + dedup | F_perfect_predictor | 113.637 | 902.879 | 902.879 | -0.027% |
| native | 6/60s | 4 | answer | original | A_none | 112.990 | 902.635 | 902.635 | +0.000% |
| native | 6/60s | 4 | answer | original | B_ungated | 116.348 | 905.033 | 905.033 | -0.265% |
| native | 6/60s | 4 | answer | original | D_jev_all | 112.990 | 902.635 | 902.810 | -0.019% |
| native | 6/60s | 4 | answer | original | E_pipeline | 112.341 | 883.166 | 883.166 | +2.302% |
| native | 6/60s | 4 | answer | original | F_perfect_predictor | 113.637 | 902.879 | 902.879 | -0.027% |
| native | 6/60s | 4 | answer | one extra action + dedup | A_none | 112.990 | 902.635 | 902.635 | +0.000% |
| native | 6/60s | 4 | answer | one extra action + dedup | B_ungated | 118.347 | 924.522 | 924.522 | -2.285% |
| native | 6/60s | 4 | answer | one extra action + dedup | D_jev_all | 113.640 | 902.635 | 902.810 | -0.019% |
| native | 6/60s | 4 | answer | one extra action + dedup | E_pipeline | 112.341 | 883.166 | 883.166 | +2.302% |
| native | 6/60s | 4 | answer | one extra action + dedup | F_perfect_predictor | 113.637 | 902.879 | 902.879 | -0.027% |
| native | 6/60s | 8 | drain | original | A_none | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | drain | original | B_ungated | 212.804 | 902.151 | 902.151 | -0.178% |
| native | 6/60s | 8 | drain | original | D_jev_all | 212.160 | 901.516 | 901.516 | -0.107% |
| native | 6/60s | 8 | drain | original | E_pipeline | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | drain | original | F_perfect_predictor | 212.466 | 901.516 | 901.516 | -0.107% |
| native | 6/60s | 8 | drain | one extra action + dedup | A_none | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | drain | one extra action + dedup | B_ungated | 213.454 | 902.361 | 902.361 | -0.201% |
| native | 6/60s | 8 | drain | one extra action + dedup | D_jev_all | 212.160 | 901.516 | 901.516 | -0.107% |
| native | 6/60s | 8 | drain | one extra action + dedup | E_pipeline | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | drain | one extra action + dedup | F_perfect_predictor | 212.466 | 901.516 | 901.516 | -0.107% |
| native | 6/60s | 8 | answer | original | A_none | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | answer | original | B_ungated | 212.491 | 901.201 | 901.201 | -0.072% |
| native | 6/60s | 8 | answer | original | D_jev_all | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | answer | original | E_pipeline | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | answer | original | F_perfect_predictor | 212.466 | 901.516 | 901.516 | -0.107% |
| native | 6/60s | 8 | answer | one extra action + dedup | A_none | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | answer | one extra action + dedup | B_ungated | 213.759 | 903.015 | 903.015 | -0.273% |
| native | 6/60s | 8 | answer | one extra action + dedup | D_jev_all | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | answer | one extra action + dedup | E_pipeline | 212.469 | 900.547 | 900.547 | +0.000% |
| native | 6/60s | 8 | answer | one extra action + dedup | F_perfect_predictor | 212.466 | 901.516 | 901.516 | -0.107% |
| scale10 | 10000/1s | 1 | drain | original | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 10000/1s | 1 | drain | original | B_ungated | 26.380 | 820.859 | 822.501 | +9.038% |
| scale10 | 10000/1s | 1 | drain | original | D_jev_all | 26.782 | 835.492 | 837.217 | +7.125% |
| scale10 | 10000/1s | 1 | drain | original | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 10000/1s | 1 | drain | original | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 10000/1s | 1 | drain | one extra action + dedup | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 10000/1s | 1 | drain | one extra action + dedup | B_ungated | 26.600 | 827.476 | 829.119 | +8.168% |
| scale10 | 10000/1s | 1 | drain | one extra action + dedup | D_jev_all | 26.782 | 835.492 | 837.217 | +7.125% |
| scale10 | 10000/1s | 1 | drain | one extra action + dedup | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 10000/1s | 1 | drain | one extra action + dedup | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 10000/1s | 1 | answer | original | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 10000/1s | 1 | answer | original | B_ungated | 26.380 | 791.396 | 793.038 | +13.090% |
| scale10 | 10000/1s | 1 | answer | original | D_jev_all | 26.782 | 803.446 | 805.170 | +11.393% |
| scale10 | 10000/1s | 1 | answer | original | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 10000/1s | 1 | answer | original | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 10000/1s | 1 | answer | one extra action + dedup | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 10000/1s | 1 | answer | one extra action + dedup | B_ungated | 26.600 | 798.013 | 799.655 | +12.154% |
| scale10 | 10000/1s | 1 | answer | one extra action + dedup | D_jev_all | 26.782 | 803.446 | 805.170 | +11.393% |
| scale10 | 10000/1s | 1 | answer | one extra action + dedup | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 10000/1s | 1 | answer | one extra action + dedup | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 10000/1s | 2 | drain | original | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 10000/1s | 2 | drain | original | B_ungated | 26.380 | 412.595 | 414.238 | +9.194% |
| scale10 | 10000/1s | 2 | drain | original | D_jev_all | 26.852 | 421.313 | 423.057 | +6.926% |
| scale10 | 10000/1s | 2 | drain | original | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 10000/1s | 2 | drain | original | F_perfect_predictor | 22.025 | 334.132 | 334.132 | +35.377% |
| scale10 | 10000/1s | 2 | drain | one extra action + dedup | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 10000/1s | 2 | drain | one extra action + dedup | B_ungated | 26.600 | 416.083 | 417.725 | +8.282% |
| scale10 | 10000/1s | 2 | drain | one extra action + dedup | D_jev_all | 26.852 | 421.313 | 423.057 | +6.926% |
| scale10 | 10000/1s | 2 | drain | one extra action + dedup | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 10000/1s | 2 | drain | one extra action + dedup | F_perfect_predictor | 22.025 | 334.132 | 334.132 | +35.377% |
| scale10 | 10000/1s | 2 | answer | original | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 10000/1s | 2 | answer | original | B_ungated | 26.380 | 397.878 | 399.520 | +13.216% |
| scale10 | 10000/1s | 2 | answer | original | D_jev_all | 26.786 | 405.394 | 405.394 | +11.579% |
| scale10 | 10000/1s | 2 | answer | original | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 10000/1s | 2 | answer | original | F_perfect_predictor | 22.025 | 334.132 | 334.132 | +35.377% |
| scale10 | 10000/1s | 2 | answer | one extra action + dedup | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 10000/1s | 2 | answer | one extra action + dedup | B_ungated | 26.600 | 402.130 | 402.130 | +12.479% |
| scale10 | 10000/1s | 2 | answer | one extra action + dedup | D_jev_all | 26.786 | 405.394 | 405.394 | +11.579% |
| scale10 | 10000/1s | 2 | answer | one extra action + dedup | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 10000/1s | 2 | answer | one extra action + dedup | F_perfect_predictor | 22.025 | 334.132 | 334.132 | +35.377% |
| scale10 | 10000/1s | 4 | drain | original | A_none | 29.895 | 234.039 | 234.039 | +0.000% |
| scale10 | 10000/1s | 4 | drain | original | B_ungated | 26.380 | 216.047 | 216.724 | +7.993% |
| scale10 | 10000/1s | 4 | drain | original | D_jev_all | 26.803 | 221.268 | 222.029 | +5.386% |
| scale10 | 10000/1s | 4 | drain | original | E_pipeline | 26.111 | 211.729 | 211.729 | +10.538% |
| scale10 | 10000/1s | 4 | drain | original | F_perfect_predictor | 22.025 | 193.908 | 193.908 | +21.606% |
| scale10 | 10000/1s | 4 | drain | one extra action + dedup | A_none | 29.895 | 234.039 | 234.039 | +0.000% |
| scale10 | 10000/1s | 4 | drain | one extra action + dedup | B_ungated | 26.600 | 219.226 | 219.903 | +6.409% |
| scale10 | 10000/1s | 4 | drain | one extra action + dedup | D_jev_all | 26.803 | 221.268 | 222.029 | +5.386% |
| scale10 | 10000/1s | 4 | drain | one extra action + dedup | E_pipeline | 26.111 | 211.729 | 211.729 | +10.538% |
| scale10 | 10000/1s | 4 | drain | one extra action + dedup | F_perfect_predictor | 22.025 | 193.908 | 193.908 | +21.606% |
| scale10 | 10000/1s | 4 | answer | original | A_none | 29.895 | 234.039 | 234.039 | +0.000% |
| scale10 | 10000/1s | 4 | answer | original | B_ungated | 26.380 | 211.729 | 213.083 | +9.849% |
| scale10 | 10000/1s | 4 | answer | original | D_jev_all | 26.915 | 214.792 | 216.314 | +8.183% |
| scale10 | 10000/1s | 4 | answer | original | E_pipeline | 26.111 | 211.729 | 211.729 | +10.538% |
| scale10 | 10000/1s | 4 | answer | original | F_perfect_predictor | 22.025 | 193.908 | 193.908 | +21.606% |
| scale10 | 10000/1s | 4 | answer | one extra action + dedup | A_none | 29.895 | 234.039 | 234.039 | +0.000% |
| scale10 | 10000/1s | 4 | answer | one extra action + dedup | B_ungated | 26.600 | 212.143 | 213.497 | +9.627% |
| scale10 | 10000/1s | 4 | answer | one extra action + dedup | D_jev_all | 26.915 | 214.792 | 216.314 | +8.183% |
| scale10 | 10000/1s | 4 | answer | one extra action + dedup | E_pipeline | 26.111 | 211.729 | 211.729 | +10.538% |
| scale10 | 10000/1s | 4 | answer | one extra action + dedup | F_perfect_predictor | 22.025 | 193.908 | 193.908 | +21.606% |
| scale10 | 10000/1s | 8 | drain | original | A_none | 29.895 | 185.541 | 185.541 | +0.000% |
| scale10 | 10000/1s | 8 | drain | original | B_ungated | 26.380 | 184.352 | 186.382 | -0.439% |
| scale10 | 10000/1s | 8 | drain | original | D_jev_all | 26.892 | 184.981 | 187.265 | -0.907% |
| scale10 | 10000/1s | 8 | drain | original | E_pipeline | 26.111 | 182.911 | 182.911 | +1.438% |
| scale10 | 10000/1s | 8 | drain | original | F_perfect_predictor | 22.025 | 175.090 | 175.090 | +5.940% |
| scale10 | 10000/1s | 8 | drain | one extra action + dedup | A_none | 29.895 | 185.541 | 185.541 | +0.000% |
| scale10 | 10000/1s | 8 | drain | one extra action + dedup | B_ungated | 26.600 | 184.352 | 186.382 | -0.439% |
| scale10 | 10000/1s | 8 | drain | one extra action + dedup | D_jev_all | 26.892 | 184.981 | 187.265 | -0.907% |
| scale10 | 10000/1s | 8 | drain | one extra action + dedup | E_pipeline | 26.111 | 182.911 | 182.911 | +1.438% |
| scale10 | 10000/1s | 8 | drain | one extra action + dedup | F_perfect_predictor | 22.025 | 175.090 | 175.090 | +5.940% |
| scale10 | 10000/1s | 8 | answer | original | A_none | 29.895 | 185.541 | 185.541 | +0.000% |
| scale10 | 10000/1s | 8 | answer | original | B_ungated | 26.380 | 182.911 | 184.941 | +0.323% |
| scale10 | 10000/1s | 8 | answer | original | D_jev_all | 26.826 | 183.407 | 185.691 | -0.083% |
| scale10 | 10000/1s | 8 | answer | original | E_pipeline | 26.111 | 182.911 | 182.911 | +1.438% |
| scale10 | 10000/1s | 8 | answer | original | F_perfect_predictor | 22.025 | 175.090 | 175.090 | +5.940% |
| scale10 | 10000/1s | 8 | answer | one extra action + dedup | A_none | 29.895 | 185.541 | 185.541 | +0.000% |
| scale10 | 10000/1s | 8 | answer | one extra action + dedup | B_ungated | 26.600 | 182.911 | 184.941 | +0.323% |
| scale10 | 10000/1s | 8 | answer | one extra action + dedup | D_jev_all | 26.826 | 183.407 | 185.691 | -0.083% |
| scale10 | 10000/1s | 8 | answer | one extra action + dedup | E_pipeline | 26.111 | 182.911 | 182.911 | +1.438% |
| scale10 | 10000/1s | 8 | answer | one extra action + dedup | F_perfect_predictor | 22.025 | 175.090 | 175.090 | +5.940% |
| scale10 | 12/30s | 1 | drain | original | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 12/30s | 1 | drain | original | B_ungated | 26.426 | 822.234 | 823.876 | +8.856% |
| scale10 | 12/30s | 1 | drain | original | D_jev_all | 26.804 | 836.173 | 837.898 | +7.037% |
| scale10 | 12/30s | 1 | drain | original | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 12/30s | 1 | drain | original | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 12/30s | 1 | drain | one extra action + dedup | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 12/30s | 1 | drain | one extra action + dedup | B_ungated | 26.626 | 828.239 | 829.881 | +8.068% |
| scale10 | 12/30s | 1 | drain | one extra action + dedup | D_jev_all | 26.804 | 836.173 | 837.898 | +7.037% |
| scale10 | 12/30s | 1 | drain | one extra action + dedup | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 12/30s | 1 | drain | one extra action + dedup | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 12/30s | 1 | answer | original | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 12/30s | 1 | answer | original | B_ungated | 26.520 | 795.606 | 797.249 | +12.492% |
| scale10 | 12/30s | 1 | answer | original | D_jev_all | 26.849 | 805.459 | 807.184 | +11.113% |
| scale10 | 12/30s | 1 | answer | original | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 12/30s | 1 | answer | original | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 12/30s | 1 | answer | one extra action + dedup | A_none | 29.895 | 896.838 | 896.838 | +0.000% |
| scale10 | 12/30s | 1 | answer | one extra action + dedup | B_ungated | 26.671 | 800.118 | 801.761 | +11.860% |
| scale10 | 12/30s | 1 | answer | one extra action + dedup | D_jev_all | 26.849 | 805.459 | 807.184 | +11.113% |
| scale10 | 12/30s | 1 | answer | one extra action + dedup | E_pipeline | 26.111 | 783.315 | 783.315 | +14.493% |
| scale10 | 12/30s | 1 | answer | one extra action + dedup | F_perfect_predictor | 22.025 | 660.750 | 660.750 | +35.730% |
| scale10 | 12/30s | 2 | drain | original | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 12/30s | 2 | drain | original | B_ungated | 30.279 | 473.119 | 474.761 | -4.711% |
| scale10 | 12/30s | 2 | drain | original | D_jev_all | 29.013 | 452.928 | 454.672 | -0.451% |
| scale10 | 12/30s | 2 | drain | original | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 12/30s | 2 | drain | original | F_perfect_predictor | 22.037 | 334.277 | 334.277 | +35.319% |
| scale10 | 12/30s | 2 | drain | one extra action + dedup | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 12/30s | 2 | drain | one extra action + dedup | B_ungated | 30.319 | 473.119 | 474.761 | -4.711% |
| scale10 | 12/30s | 2 | drain | one extra action + dedup | D_jev_all | 29.013 | 452.928 | 454.672 | -0.451% |
| scale10 | 12/30s | 2 | drain | one extra action + dedup | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 12/30s | 2 | drain | one extra action + dedup | F_perfect_predictor | 22.037 | 334.277 | 334.277 | +35.319% |
| scale10 | 12/30s | 2 | answer | original | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 12/30s | 2 | answer | original | B_ungated | 30.657 | 468.129 | 469.772 | -3.696% |
| scale10 | 12/30s | 2 | answer | original | D_jev_all | 28.814 | 434.278 | 434.630 | +4.084% |
| scale10 | 12/30s | 2 | answer | original | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 12/30s | 2 | answer | original | F_perfect_predictor | 22.037 | 334.277 | 334.277 | +35.319% |
| scale10 | 12/30s | 2 | answer | one extra action + dedup | A_none | 29.895 | 452.328 | 452.328 | +0.000% |
| scale10 | 12/30s | 2 | answer | one extra action + dedup | B_ungated | 30.935 | 468.129 | 469.772 | -3.696% |
| scale10 | 12/30s | 2 | answer | one extra action + dedup | D_jev_all | 28.814 | 434.278 | 434.630 | +4.084% |
| scale10 | 12/30s | 2 | answer | one extra action + dedup | E_pipeline | 26.111 | 395.051 | 395.051 | +14.497% |
| scale10 | 12/30s | 2 | answer | one extra action + dedup | F_perfect_predictor | 22.037 | 334.277 | 334.277 | +35.319% |
| scale10 | 12/30s | 4 | drain | original | A_none | 31.508 | 245.391 | 245.391 | +0.000% |
| scale10 | 12/30s | 4 | drain | original | B_ungated | 49.920 | 406.982 | 406.982 | -39.620% |
| scale10 | 12/30s | 4 | drain | original | D_jev_all | 37.613 | 300.556 | 300.556 | -18.357% |
| scale10 | 12/30s | 4 | drain | original | E_pipeline | 29.655 | 232.823 | 232.823 | +5.395% |
| scale10 | 12/30s | 4 | drain | original | F_perfect_predictor | 29.150 | 227.673 | 227.673 | +7.823% |
| scale10 | 12/30s | 4 | drain | one extra action + dedup | A_none | 31.508 | 245.391 | 245.391 | +0.000% |
| scale10 | 12/30s | 4 | drain | one extra action + dedup | B_ungated | 50.060 | 406.982 | 406.982 | -39.620% |
| scale10 | 12/30s | 4 | drain | one extra action + dedup | D_jev_all | 37.613 | 300.556 | 300.556 | -18.357% |
| scale10 | 12/30s | 4 | drain | one extra action + dedup | E_pipeline | 29.651 | 232.823 | 232.823 | +5.395% |
| scale10 | 12/30s | 4 | drain | one extra action + dedup | F_perfect_predictor | 29.150 | 227.673 | 227.673 | +7.823% |
| scale10 | 12/30s | 4 | answer | original | A_none | 31.508 | 245.391 | 245.391 | +0.000% |
| scale10 | 12/30s | 4 | answer | original | B_ungated | 50.464 | 404.169 | 404.169 | -39.209% |
| scale10 | 12/30s | 4 | answer | original | D_jev_all | 38.532 | 306.408 | 306.408 | -19.923% |
| scale10 | 12/30s | 4 | answer | original | E_pipeline | 29.655 | 232.823 | 232.823 | +5.395% |
| scale10 | 12/30s | 4 | answer | original | F_perfect_predictor | 29.151 | 227.673 | 227.673 | +7.823% |
| scale10 | 12/30s | 4 | answer | one extra action + dedup | A_none | 31.508 | 245.391 | 245.391 | +0.000% |
| scale10 | 12/30s | 4 | answer | one extra action + dedup | B_ungated | 51.447 | 414.169 | 414.169 | -40.751% |
| scale10 | 12/30s | 4 | answer | one extra action + dedup | D_jev_all | 38.532 | 306.408 | 306.408 | -19.923% |
| scale10 | 12/30s | 4 | answer | one extra action + dedup | E_pipeline | 29.651 | 232.823 | 232.823 | +5.395% |
| scale10 | 12/30s | 4 | answer | one extra action + dedup | F_perfect_predictor | 29.151 | 227.673 | 227.673 | +7.823% |
| scale10 | 12/30s | 8 | drain | original | A_none | 55.216 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | drain | original | B_ungated | 76.215 | 337.661 | 337.661 | -30.260% |
| scale10 | 12/30s | 8 | drain | original | D_jev_all | 56.217 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | drain | original | E_pipeline | 53.712 | 232.340 | 232.340 | +1.291% |
| scale10 | 12/30s | 8 | drain | original | F_perfect_predictor | 54.149 | 231.655 | 231.655 | +1.599% |
| scale10 | 12/30s | 8 | drain | one extra action + dedup | A_none | 55.216 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | drain | one extra action + dedup | B_ungated | 76.215 | 337.661 | 337.661 | -30.260% |
| scale10 | 12/30s | 8 | drain | one extra action + dedup | D_jev_all | 56.217 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | drain | one extra action + dedup | E_pipeline | 53.712 | 232.340 | 232.340 | +1.291% |
| scale10 | 12/30s | 8 | drain | one extra action + dedup | F_perfect_predictor | 54.149 | 231.655 | 231.655 | +1.599% |
| scale10 | 12/30s | 8 | answer | original | A_none | 55.216 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | answer | original | B_ungated | 76.578 | 337.661 | 337.661 | -30.260% |
| scale10 | 12/30s | 8 | answer | original | D_jev_all | 56.217 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | answer | original | E_pipeline | 53.712 | 232.340 | 232.340 | +1.291% |
| scale10 | 12/30s | 8 | answer | original | F_perfect_predictor | 54.149 | 231.655 | 231.655 | +1.599% |
| scale10 | 12/30s | 8 | answer | one extra action + dedup | A_none | 55.216 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | answer | one extra action + dedup | B_ungated | 76.578 | 337.661 | 337.661 | -30.260% |
| scale10 | 12/30s | 8 | answer | one extra action + dedup | D_jev_all | 56.217 | 235.424 | 235.424 | +0.000% |
| scale10 | 12/30s | 8 | answer | one extra action + dedup | E_pipeline | 53.712 | 232.340 | 232.340 | +1.291% |
| scale10 | 12/30s | 8 | answer | one extra action + dedup | F_perfect_predictor | 54.149 | 231.655 | 231.655 | +1.599% |
| scale10 | 6/60s | 1 | drain | original | A_none | 34.638 | 1039.128 | 1039.128 | +0.000% |
| scale10 | 6/60s | 1 | drain | original | B_ungated | 53.312 | 1622.716 | 1624.359 | -35.966% |
| scale10 | 6/60s | 1 | drain | original | D_jev_all | 44.647 | 1360.543 | 1362.267 | -23.702% |
| scale10 | 6/60s | 1 | drain | original | E_pipeline | 33.952 | 1018.551 | 1018.551 | +2.020% |
| scale10 | 6/60s | 1 | drain | original | F_perfect_predictor | 32.796 | 983.897 | 983.897 | +5.607% |
| scale10 | 6/60s | 1 | drain | one extra action + dedup | A_none | 34.638 | 1039.128 | 1039.128 | +0.000% |
| scale10 | 6/60s | 1 | drain | one extra action + dedup | B_ungated | 53.312 | 1622.716 | 1624.359 | -35.966% |
| scale10 | 6/60s | 1 | drain | one extra action + dedup | D_jev_all | 44.647 | 1360.543 | 1362.267 | -23.702% |
| scale10 | 6/60s | 1 | drain | one extra action + dedup | E_pipeline | 33.952 | 1018.551 | 1018.551 | +2.020% |
| scale10 | 6/60s | 1 | drain | one extra action + dedup | F_perfect_predictor | 32.796 | 983.897 | 983.897 | +5.607% |
| scale10 | 6/60s | 1 | answer | original | A_none | 34.638 | 1039.128 | 1039.128 | +0.000% |
| scale10 | 6/60s | 1 | answer | original | B_ungated | 54.091 | 1622.716 | 1624.359 | -35.966% |
| scale10 | 6/60s | 1 | answer | original | D_jev_all | 45.351 | 1360.543 | 1362.267 | -23.702% |
| scale10 | 6/60s | 1 | answer | original | E_pipeline | 33.952 | 1018.551 | 1018.551 | +2.020% |
| scale10 | 6/60s | 1 | answer | original | F_perfect_predictor | 32.797 | 983.897 | 983.897 | +5.607% |
| scale10 | 6/60s | 1 | answer | one extra action + dedup | A_none | 34.638 | 1039.128 | 1039.128 | +0.000% |
| scale10 | 6/60s | 1 | answer | one extra action + dedup | B_ungated | 54.091 | 1622.716 | 1624.359 | -35.966% |
| scale10 | 6/60s | 1 | answer | one extra action + dedup | D_jev_all | 45.351 | 1360.543 | 1362.267 | -23.702% |
| scale10 | 6/60s | 1 | answer | one extra action + dedup | E_pipeline | 33.952 | 1018.551 | 1018.551 | +2.020% |
| scale10 | 6/60s | 1 | answer | one extra action + dedup | F_perfect_predictor | 32.797 | 983.897 | 983.897 | +5.607% |
| scale10 | 6/60s | 2 | drain | original | A_none | 59.176 | 908.307 | 908.307 | +0.000% |
| scale10 | 6/60s | 2 | drain | original | B_ungated | 100.613 | 1533.468 | 1535.110 | -40.811% |
| scale10 | 6/60s | 2 | drain | original | D_jev_all | 62.960 | 968.307 | 970.582 | -6.416% |
| scale10 | 6/60s | 2 | drain | original | E_pipeline | 57.393 | 861.855 | 861.855 | +5.391% |
| scale10 | 6/60s | 2 | drain | original | F_perfect_predictor | 57.168 | 861.864 | 861.864 | +5.388% |
| scale10 | 6/60s | 2 | drain | one extra action + dedup | A_none | 59.176 | 908.307 | 908.307 | +0.000% |
| scale10 | 6/60s | 2 | drain | one extra action + dedup | B_ungated | 100.601 | 1533.468 | 1535.110 | -40.811% |
| scale10 | 6/60s | 2 | drain | one extra action + dedup | D_jev_all | 62.960 | 968.307 | 970.582 | -6.416% |
| scale10 | 6/60s | 2 | drain | one extra action + dedup | E_pipeline | 57.393 | 861.855 | 861.855 | +5.391% |
| scale10 | 6/60s | 2 | drain | one extra action + dedup | F_perfect_predictor | 57.168 | 861.864 | 861.864 | +5.388% |
| scale10 | 6/60s | 2 | answer | original | A_none | 59.176 | 908.307 | 908.307 | +0.000% |
| scale10 | 6/60s | 2 | answer | original | B_ungated | 102.202 | 1536.033 | 1536.033 | -40.848% |
| scale10 | 6/60s | 2 | answer | original | D_jev_all | 62.683 | 953.496 | 955.771 | -4.925% |
| scale10 | 6/60s | 2 | answer | original | E_pipeline | 57.393 | 861.855 | 861.855 | +5.391% |
| scale10 | 6/60s | 2 | answer | original | F_perfect_predictor | 57.168 | 861.864 | 861.864 | +5.388% |
| scale10 | 6/60s | 2 | answer | one extra action + dedup | A_none | 59.176 | 908.307 | 908.307 | +0.000% |
| scale10 | 6/60s | 2 | answer | one extra action + dedup | B_ungated | 102.117 | 1534.986 | 1536.628 | -40.871% |
| scale10 | 6/60s | 2 | answer | one extra action + dedup | D_jev_all | 62.683 | 953.496 | 955.771 | -4.925% |
| scale10 | 6/60s | 2 | answer | one extra action + dedup | E_pipeline | 57.393 | 861.855 | 861.855 | +5.391% |
| scale10 | 6/60s | 2 | answer | one extra action + dedup | F_perfect_predictor | 57.168 | 861.864 | 861.864 | +5.388% |
| scale10 | 6/60s | 4 | drain | original | A_none | 114.436 | 910.829 | 910.829 | +0.000% |
| scale10 | 6/60s | 4 | drain | original | B_ungated | 153.250 | 1216.033 | 1216.033 | -25.101% |
| scale10 | 6/60s | 4 | drain | original | D_jev_all | 115.243 | 916.280 | 916.280 | -0.593% |
| scale10 | 6/60s | 4 | drain | original | E_pipeline | 110.571 | 866.982 | 866.982 | +5.056% |
| scale10 | 6/60s | 4 | drain | original | F_perfect_predictor | 110.536 | 862.232 | 862.232 | +5.637% |
| scale10 | 6/60s | 4 | drain | one extra action + dedup | A_none | 114.436 | 910.829 | 910.829 | +0.000% |
| scale10 | 6/60s | 4 | drain | one extra action + dedup | B_ungated | 152.583 | 1216.033 | 1216.033 | -25.101% |
| scale10 | 6/60s | 4 | drain | one extra action + dedup | D_jev_all | 115.243 | 916.280 | 916.280 | -0.593% |
| scale10 | 6/60s | 4 | drain | one extra action + dedup | E_pipeline | 110.571 | 866.982 | 866.982 | +5.056% |
| scale10 | 6/60s | 4 | drain | one extra action + dedup | F_perfect_predictor | 110.536 | 862.232 | 862.232 | +5.637% |
| scale10 | 6/60s | 4 | answer | original | A_none | 114.436 | 910.829 | 910.829 | +0.000% |
| scale10 | 6/60s | 4 | answer | original | B_ungated | 153.615 | 1216.033 | 1216.033 | -25.101% |
| scale10 | 6/60s | 4 | answer | original | D_jev_all | 115.269 | 916.280 | 916.280 | -0.593% |
| scale10 | 6/60s | 4 | answer | original | E_pipeline | 110.571 | 866.982 | 866.982 | +5.056% |
| scale10 | 6/60s | 4 | answer | original | F_perfect_predictor | 110.537 | 862.232 | 862.232 | +5.637% |
| scale10 | 6/60s | 4 | answer | one extra action + dedup | A_none | 114.436 | 910.829 | 910.829 | +0.000% |
| scale10 | 6/60s | 4 | answer | one extra action + dedup | B_ungated | 152.948 | 1216.033 | 1216.033 | -25.101% |
| scale10 | 6/60s | 4 | answer | one extra action + dedup | D_jev_all | 115.269 | 916.280 | 916.280 | -0.593% |
| scale10 | 6/60s | 4 | answer | one extra action + dedup | E_pipeline | 110.571 | 866.982 | 866.982 | +5.056% |
| scale10 | 6/60s | 4 | answer | one extra action + dedup | F_perfect_predictor | 110.537 | 862.232 | 862.232 | +5.637% |
| scale10 | 6/60s | 8 | drain | original | A_none | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | drain | original | B_ungated | 218.487 | 936.014 | 936.014 | -2.462% |
| scale10 | 6/60s | 8 | drain | original | D_jev_all | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | drain | original | E_pipeline | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | drain | original | F_perfect_predictor | 213.829 | 894.051 | 894.051 | +2.093% |
| scale10 | 6/60s | 8 | drain | one extra action + dedup | A_none | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | drain | one extra action + dedup | B_ungated | 218.487 | 936.014 | 936.014 | -2.462% |
| scale10 | 6/60s | 8 | drain | one extra action + dedup | D_jev_all | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | drain | one extra action + dedup | E_pipeline | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | drain | one extra action + dedup | F_perfect_predictor | 213.829 | 894.051 | 894.051 | +2.093% |
| scale10 | 6/60s | 8 | answer | original | A_none | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | answer | original | B_ungated | 218.487 | 936.014 | 936.014 | -2.462% |
| scale10 | 6/60s | 8 | answer | original | D_jev_all | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | answer | original | E_pipeline | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | answer | original | F_perfect_predictor | 213.829 | 894.051 | 894.051 | +2.093% |
| scale10 | 6/60s | 8 | answer | one extra action + dedup | A_none | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | answer | one extra action + dedup | B_ungated | 218.487 | 936.014 | 936.014 | -2.462% |
| scale10 | 6/60s | 8 | answer | one extra action + dedup | D_jev_all | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | answer | one extra action + dedup | E_pipeline | 214.707 | 912.132 | 912.132 | +0.000% |
| scale10 | 6/60s | 8 | answer | one extra action + dedup | F_perfect_predictor | 213.829 | 894.051 | 894.051 | +2.093% |

## Repeated-stream diagnostic

Answer release, original lifetime. Mean questions/s over three orders, converted to improvement against the same repeated no-speculation stream. Interior gain uses the 10%–90% interval of ordered answer finishes; it reduces endpoints without proving stationarity.

| Duration | Quota | Workers | Tasks | Policy | All-work s | Throughput gain | Interior throughput gain |
|---|---|---:|---:|---|---:|---:|---:|
| native | 10000/1s | 1 | 30 | B_ungated | 312.328 | +1.273% | +2.147% |
| native | 10000/1s | 1 | 30 | D_jev_all | 314.721 | +0.503% | +0.856% |
| native | 10000/1s | 1 | 30 | F_full_generation | 311.474 | +1.551% | +2.260% |
| native | 10000/1s | 1 | 30 | G_zero_overhead | 273.499 | +15.651% | +24.607% |
| native | 10000/1s | 1 | 300 | B_ungated | 3120.089 | +1.377% | +1.388% |
| native | 10000/1s | 1 | 300 | D_jev_all | 3144.708 | +0.583% | +0.589% |
| native | 10000/1s | 1 | 300 | F_full_generation | 3111.546 | +1.655% | +1.667% |
| native | 10000/1s | 1 | 300 | G_zero_overhead | 2734.988 | +15.651% | +15.651% |
| native | 10000/1s | 2 | 30 | B_ungated | 174.155 | +0.405% | +2.214% |
| native | 10000/1s | 2 | 30 | D_jev_all | 175.309 | -0.203% | +1.349% |
| native | 10000/1s | 2 | 30 | F_full_generation | 174.118 | +0.457% | +2.870% |
| native | 10000/1s | 2 | 30 | G_zero_overhead | 167.931 | +4.033% | +35.011% |
| native | 10000/1s | 2 | 300 | B_ungated | 1577.863 | +1.200% | +1.482% |
| native | 10000/1s | 2 | 300 | D_jev_all | 1589.740 | +0.445% | +0.657% |
| native | 10000/1s | 2 | 300 | F_full_generation | 1573.410 | +1.487% | +1.753% |
| native | 10000/1s | 2 | 300 | G_zero_overhead | 1383.535 | +15.414% | +15.721% |
| native | 10000/1s | 4 | 30 | B_ungated | 163.666 | -0.023% | +2.000% |
| native | 10000/1s | 4 | 30 | D_jev_all | 164.030 | -0.234% | +1.496% |
| native | 10000/1s | 4 | 30 | F_full_generation | 162.963 | +0.408% | +4.155% |
| native | 10000/1s | 4 | 30 | G_zero_overhead | 159.871 | +2.324% | +35.268% |
| native | 10000/1s | 4 | 300 | B_ungated | 847.281 | +1.179% | +1.541% |
| native | 10000/1s | 4 | 300 | D_jev_all | 854.175 | +0.364% | +0.655% |
| native | 10000/1s | 4 | 300 | F_full_generation | 844.934 | +1.460% | +1.907% |
| native | 10000/1s | 4 | 300 | G_zero_overhead | 750.578 | +14.214% | +16.186% |
| native | 10000/1s | 8 | 30 | B_ungated | 158.143 | -0.242% | +2.275% |
| native | 10000/1s | 8 | 30 | D_jev_all | 158.143 | -0.242% | +0.949% |
| native | 10000/1s | 8 | 30 | F_full_generation | 157.480 | +0.178% | +4.475% |
| native | 10000/1s | 8 | 30 | G_zero_overhead | 155.309 | +1.576% | +39.913% |
| native | 10000/1s | 8 | 300 | B_ungated | 481.042 | +1.090% | +1.724% |
| native | 10000/1s | 8 | 300 | D_jev_all | 485.232 | +0.217% | +0.413% |
| native | 10000/1s | 8 | 300 | F_full_generation | 479.561 | +1.401% | +2.023% |
| native | 10000/1s | 8 | 300 | G_zero_overhead | 428.760 | +13.415% | +19.361% |
| native | 12/30s | 1 | 30 | B_ungated | 398.729 | -10.249% | -11.878% |
| native | 12/30s | 1 | 30 | D_jev_all | 366.389 | -2.342% | -0.869% |
| native | 12/30s | 1 | 30 | F_full_generation | 355.846 | +0.566% | +0.589% |
| native | 12/30s | 1 | 30 | G_zero_overhead | 344.053 | +4.001% | +4.556% |
| native | 12/30s | 1 | 300 | B_ungated | 3993.693 | -9.895% | -9.972% |
| native | 12/30s | 1 | 300 | D_jev_all | 3684.175 | -2.339% | -2.102% |
| native | 12/30s | 1 | 300 | F_full_generation | 3594.283 | +0.100% | +0.128% |
| native | 12/30s | 1 | 300 | G_zero_overhead | 3584.053 | +0.385% | +0.000% |
| native | 12/30s | 2 | 30 | B_ungated | 248.049 | -11.459% | -8.634% |
| native | 12/30s | 2 | 30 | D_jev_all | 220.277 | -0.285% | -1.483% |
| native | 12/30s | 2 | 30 | F_full_generation | 218.961 | +0.321% | +4.242% |
| native | 12/30s | 2 | 30 | G_zero_overhead | 215.937 | +1.721% | +5.379% |
| native | 12/30s | 2 | 300 | B_ungated | 2654.852 | -14.529% | -14.531% |
| native | 12/30s | 2 | 300 | D_jev_all | 2324.921 | -2.406% | -1.823% |
| native | 12/30s | 2 | 300 | F_full_generation | 2241.631 | +1.218% | +1.450% |
| native | 12/30s | 2 | 300 | G_zero_overhead | 2197.513 | +3.248% | +3.284% |
| native | 12/30s | 4 | 30 | B_ungated | 245.026 | -11.876% | -1.283% |
| native | 12/30s | 4 | 30 | D_jev_all | 216.061 | -0.058% | +0.000% |
| native | 12/30s | 4 | 30 | F_full_generation | 216.032 | -0.044% | +4.477% |
| native | 12/30s | 4 | 30 | G_zero_overhead | 213.767 | +1.013% | +20.758% |
| native | 12/30s | 4 | 300 | B_ungated | 2533.863 | -10.913% | -10.389% |
| native | 12/30s | 4 | 300 | D_jev_all | 2257.831 | -0.025% | -0.001% |
| native | 12/30s | 4 | 300 | F_full_generation | 2253.578 | +0.164% | +0.581% |
| native | 12/30s | 4 | 300 | G_zero_overhead | 2213.927 | +1.961% | +2.766% |
| native | 12/30s | 8 | 30 | B_ungated | 233.689 | -7.459% | -1.008% |
| native | 12/30s | 8 | 30 | D_jev_all | 215.753 | +0.000% | +0.000% |
| native | 12/30s | 8 | 30 | F_full_generation | 215.476 | +0.130% | -0.100% |
| native | 12/30s | 8 | 30 | G_zero_overhead | 213.771 | +0.929% | -4.363% |
| native | 12/30s | 8 | 300 | B_ungated | 2393.132 | -5.750% | -5.657% |
| native | 12/30s | 8 | 300 | D_jev_all | 2255.476 | +0.000% | +0.000% |
| native | 12/30s | 8 | 300 | F_full_generation | 2255.222 | +0.011% | +0.026% |
| native | 12/30s | 8 | 300 | G_zero_overhead | 2243.093 | +0.555% | +0.585% |
| native | 6/60s | 1 | 30 | B_ungated | 1087.086 | -11.108% | -12.883% |
| native | 6/60s | 1 | 30 | D_jev_all | 967.347 | -0.105% | +0.000% |
| native | 6/60s | 1 | 30 | F_full_generation | 964.264 | +0.215% | +2.684% |
| native | 6/60s | 1 | 30 | G_zero_overhead | 944.509 | +2.386% | +3.044% |
| native | 6/60s | 1 | 300 | B_ungated | 11347.086 | -10.582% | -10.526% |
| native | 6/60s | 1 | 300 | D_jev_all | 10149.257 | -0.029% | +0.006% |
| native | 6/60s | 1 | 300 | F_full_generation | 9604.707 | +5.639% | +6.237% |
| native | 6/60s | 1 | 300 | G_zero_overhead | 9584.509 | +5.863% | +6.250% |
| native | 6/60s | 2 | 30 | B_ungated | 984.899 | -8.384% | -5.144% |
| native | 6/60s | 2 | 30 | D_jev_all | 901.994 | -0.039% | +0.000% |
| native | 6/60s | 2 | 30 | F_full_generation | 883.791 | +2.113% | +2.467% |
| native | 6/60s | 2 | 30 | G_zero_overhead | 843.964 | +6.834% | +8.632% |
| native | 6/60s | 2 | 300 | B_ungated | 10065.880 | -9.919% | -9.874% |
| native | 6/60s | 2 | 300 | D_jev_all | 9066.381 | -0.013% | -0.250% |
| native | 6/60s | 2 | 300 | F_full_generation | 8984.302 | +0.901% | +0.849% |
| native | 6/60s | 2 | 300 | G_zero_overhead | 8943.485 | +1.361% | +1.387% |
| native | 6/60s | 4 | 30 | B_ungated | 905.033 | -0.265% | -2.349% |
| native | 6/60s | 4 | 30 | D_jev_all | 902.810 | -0.019% | +0.000% |
| native | 6/60s | 4 | 30 | F_full_generation | 902.879 | -0.027% | +0.037% |
| native | 6/60s | 4 | 30 | G_zero_overhead | 883.329 | +2.285% | +2.633% |
| native | 6/60s | 4 | 300 | B_ungated | 9345.033 | -2.995% | -2.693% |
| native | 6/60s | 4 | 300 | D_jev_all | 9065.033 | +0.000% | -0.266% |
| native | 6/60s | 4 | 300 | F_full_generation | 9025.880 | +0.435% | +0.277% |
| native | 6/60s | 4 | 300 | G_zero_overhead | 8983.329 | +0.910% | +1.104% |
| native | 6/60s | 8 | 30 | B_ungated | 901.201 | -0.072% | +0.000% |
| native | 6/60s | 8 | 30 | D_jev_all | 900.547 | +0.000% | +0.000% |
| native | 6/60s | 8 | 30 | F_full_generation | 901.516 | -0.107% | +0.000% |
| native | 6/60s | 8 | 30 | G_zero_overhead | 881.684 | +2.238% | +2.636% |
| native | 6/60s | 8 | 300 | B_ungated | 9083.853 | -0.212% | +0.000% |
| native | 6/60s | 8 | 300 | D_jev_all | 9064.508 | +0.000% | +0.000% |
| native | 6/60s | 8 | 300 | F_full_generation | 9064.504 | +0.000% | +0.000% |
| native | 6/60s | 8 | 300 | G_zero_overhead | 9063.171 | +0.015% | +0.000% |
| scale10 | 10000/1s | 1 | 30 | B_ungated | 793.038 | +13.090% | +14.722% |
| scale10 | 10000/1s | 1 | 30 | D_jev_all | 807.959 | +11.001% | +12.689% |
| scale10 | 10000/1s | 1 | 30 | F_full_generation | 660.827 | +35.715% | +39.085% |
| scale10 | 10000/1s | 1 | 30 | G_zero_overhead | 609.605 | +47.118% | +51.937% |
| scale10 | 10000/1s | 1 | 300 | B_ungated | 7915.598 | +13.300% | +13.324% |
| scale10 | 10000/1s | 1 | 300 | D_jev_all | 8033.935 | +11.632% | +11.747% |
| scale10 | 10000/1s | 1 | 300 | F_full_generation | 6607.578 | +35.729% | +35.730% |
| scale10 | 10000/1s | 1 | 300 | G_zero_overhead | 6096.052 | +47.118% | +47.118% |
| scale10 | 10000/1s | 2 | 30 | B_ungated | 399.520 | +13.216% | +13.319% |
| scale10 | 10000/1s | 2 | 30 | D_jev_all | 405.511 | +11.551% | +12.133% |
| scale10 | 10000/1s | 2 | 30 | F_full_generation | 334.208 | +35.346% | +35.309% |
| scale10 | 10000/1s | 2 | 30 | G_zero_overhead | 307.440 | +47.124% | +46.852% |
| scale10 | 10000/1s | 2 | 300 | B_ungated | 3960.642 | +13.313% | +13.296% |
| scale10 | 10000/1s | 2 | 300 | D_jev_all | 4026.693 | +11.455% | +11.532% |
| scale10 | 10000/1s | 2 | 300 | F_full_generation | 3307.117 | +35.705% | +35.702% |
| scale10 | 10000/1s | 2 | 300 | G_zero_overhead | 3050.657 | +47.114% | +47.096% |
| scale10 | 10000/1s | 4 | 30 | B_ungated | 213.083 | +9.849% | +13.073% |
| scale10 | 10000/1s | 4 | 30 | D_jev_all | 215.167 | +8.761% | +11.195% |
| scale10 | 10000/1s | 4 | 30 | F_full_generation | 193.908 | +21.606% | +45.573% |
| scale10 | 10000/1s | 4 | 30 | G_zero_overhead | 188.869 | +24.699% | +60.676% |
| scale10 | 10000/1s | 4 | 300 | B_ungated | 1992.701 | +13.117% | +13.286% |
| scale10 | 10000/1s | 4 | 300 | D_jev_all | 2025.330 | +11.294% | +11.390% |
| scale10 | 10000/1s | 4 | 300 | F_full_generation | 1681.792 | +34.038% | +35.776% |
| scale10 | 10000/1s | 4 | 300 | G_zero_overhead | 1559.560 | +44.545% | +47.124% |
| scale10 | 10000/1s | 8 | 30 | B_ungated | 184.941 | +0.323% | +17.822% |
| scale10 | 10000/1s | 8 | 30 | D_jev_all | 185.691 | -0.083% | +12.853% |
| scale10 | 10000/1s | 8 | 30 | F_full_generation | 175.090 | +5.940% | +56.006% |
| scale10 | 10000/1s | 8 | 30 | G_zero_overhead | 172.354 | +7.621% | +72.796% |
| scale10 | 10000/1s | 8 | 300 | B_ungated | 1066.616 | +11.549% | +13.131% |
| scale10 | 10000/1s | 8 | 300 | D_jev_all | 1082.324 | +9.930% | +11.376% |
| scale10 | 10000/1s | 8 | 300 | F_full_generation | 910.430 | +30.687% | +35.419% |
| scale10 | 10000/1s | 8 | 300 | G_zero_overhead | 847.367 | +40.413% | +46.711% |
| scale10 | 12/30s | 1 | 30 | B_ungated | 797.249 | +12.492% | +14.722% |
| scale10 | 12/30s | 1 | 30 | D_jev_all | 807.959 | +11.001% | +12.689% |
| scale10 | 12/30s | 1 | 30 | F_full_generation | 660.827 | +35.715% | +39.085% |
| scale10 | 12/30s | 1 | 30 | G_zero_overhead | 609.605 | +47.118% | +51.937% |
| scale10 | 12/30s | 1 | 300 | B_ungated | 7927.484 | +13.130% | +13.195% |
| scale10 | 12/30s | 1 | 300 | D_jev_all | 8032.506 | +11.651% | +11.772% |
| scale10 | 12/30s | 1 | 300 | F_full_generation | 6607.578 | +35.729% | +35.730% |
| scale10 | 12/30s | 1 | 300 | G_zero_overhead | 6096.052 | +47.118% | +47.118% |
| scale10 | 12/30s | 2 | 30 | B_ungated | 469.772 | -3.696% | -3.016% |
| scale10 | 12/30s | 2 | 30 | D_jev_all | 434.992 | +4.027% | +4.034% |
| scale10 | 12/30s | 2 | 30 | F_full_generation | 334.353 | +35.288% | +35.235% |
| scale10 | 12/30s | 2 | 30 | G_zero_overhead | 311.454 | +45.228% | +44.552% |
| scale10 | 12/30s | 2 | 300 | B_ungated | 4609.772 | -2.566% | -2.399% |
| scale10 | 12/30s | 2 | 300 | D_jev_all | 4382.708 | +2.416% | +2.256% |
| scale10 | 12/30s | 2 | 300 | F_full_generation | 3308.477 | +35.650% | +35.622% |
| scale10 | 12/30s | 2 | 300 | G_zero_overhead | 3084.860 | +45.487% | +45.465% |
| scale10 | 12/30s | 4 | 30 | B_ungated | 404.169 | -39.209% | -39.590% |
| scale10 | 12/30s | 4 | 30 | D_jev_all | 291.544 | -15.837% | -14.644% |
| scale10 | 12/30s | 4 | 30 | F_full_generation | 227.673 | +7.823% | +10.484% |
| scale10 | 12/30s | 4 | 30 | G_zero_overhead | 226.246 | +8.481% | +10.045% |
| scale10 | 12/30s | 4 | 300 | B_ungated | 3944.169 | -39.724% | -39.806% |
| scale10 | 12/30s | 4 | 300 | D_jev_all | 2906.855 | -18.471% | -18.386% |
| scale10 | 12/30s | 4 | 300 | F_full_generation | 2224.155 | +6.553% | +5.855% |
| scale10 | 12/30s | 4 | 300 | G_zero_overhead | 2236.455 | +5.970% | +5.445% |
| scale10 | 12/30s | 8 | 30 | B_ungated | 337.661 | -30.260% | -29.418% |
| scale10 | 12/30s | 8 | 30 | D_jev_all | 235.744 | -0.122% | +0.612% |
| scale10 | 12/30s | 8 | 30 | F_full_generation | 231.655 | +1.599% | -1.020% |
| scale10 | 12/30s | 8 | 30 | G_zero_overhead | 227.192 | +3.566% | -0.707% |
| scale10 | 12/30s | 8 | 300 | B_ungated | 3171.544 | -28.156% | -27.983% |
| scale10 | 12/30s | 8 | 300 | D_jev_all | 2290.695 | -0.546% | -0.669% |
| scale10 | 12/30s | 8 | 300 | F_full_generation | 2253.721 | +1.085% | +0.566% |
| scale10 | 12/30s | 8 | 300 | G_zero_overhead | 2267.433 | +0.474% | -0.007% |
| scale10 | 6/60s | 1 | 30 | B_ungated | 1624.359 | -35.966% | -37.124% |
| scale10 | 6/60s | 1 | 30 | D_jev_all | 1357.166 | -23.417% | -24.373% |
| scale10 | 6/60s | 1 | 30 | F_full_generation | 983.973 | +5.599% | +4.793% |
| scale10 | 6/60s | 1 | 30 | G_zero_overhead | 976.467 | +6.415% | +7.452% |
| scale10 | 6/60s | 1 | 300 | B_ungated | 16204.359 | -35.574% | -35.544% |
| scale10 | 6/60s | 1 | 300 | D_jev_all | 13803.105 | -24.434% | -24.581% |
| scale10 | 6/60s | 1 | 300 | F_full_generation | 10161.630 | +2.643% | +2.286% |
| scale10 | 6/60s | 1 | 300 | G_zero_overhead | 9883.774 | +5.529% | +5.301% |
| scale10 | 6/60s | 2 | 30 | B_ungated | 1536.033 | -40.848% | -39.640% |
| scale10 | 6/60s | 2 | 30 | D_jev_all | 965.321 | -5.829% | -8.976% |
| scale10 | 6/60s | 2 | 30 | F_full_generation | 861.940 | +5.378% | +2.468% |
| scale10 | 6/60s | 2 | 30 | G_zero_overhead | 855.766 | +6.139% | +5.009% |
| scale10 | 6/60s | 2 | 300 | B_ungated | 15936.033 | -42.987% | -43.118% |
| scale10 | 6/60s | 2 | 300 | D_jev_all | 9647.956 | -5.852% | -5.768% |
| scale10 | 6/60s | 2 | 300 | F_full_generation | 8914.750 | +1.892% | +1.733% |
| scale10 | 6/60s | 2 | 300 | G_zero_overhead | 8952.551 | +1.458% | +1.326% |
| scale10 | 6/60s | 4 | 30 | B_ungated | 1216.033 | -25.101% | -25.653% |
| scale10 | 6/60s | 4 | 30 | D_jev_all | 911.531 | -0.078% | -0.462% |
| scale10 | 6/60s | 4 | 30 | F_full_generation | 862.232 | +5.637% | +0.819% |
| scale10 | 6/60s | 4 | 30 | G_zero_overhead | 897.475 | +1.554% | +0.686% |
| scale10 | 6/60s | 4 | 300 | B_ungated | 12216.033 | -25.604% | -25.248% |
| scale10 | 6/60s | 4 | 300 | D_jev_all | 9159.348 | -0.789% | -0.344% |
| scale10 | 6/60s | 4 | 300 | F_full_generation | 8979.391 | +1.199% | +1.346% |
| scale10 | 6/60s | 4 | 300 | G_zero_overhead | 8998.659 | +0.982% | +1.116% |
| scale10 | 6/60s | 8 | 30 | B_ungated | 936.014 | -2.462% | -2.886% |
| scale10 | 6/60s | 8 | 30 | D_jev_all | 912.132 | +0.000% | +0.000% |
| scale10 | 6/60s | 8 | 30 | F_full_generation | 894.051 | +2.093% | +0.342% |
| scale10 | 6/60s | 8 | 30 | G_zero_overhead | 909.435 | +0.298% | +2.690% |
| scale10 | 6/60s | 8 | 300 | B_ungated | 9114.850 | -0.363% | +0.000% |
| scale10 | 6/60s | 8 | 300 | D_jev_all | 9081.544 | +0.000% | +0.000% |
| scale10 | 6/60s | 8 | 300 | F_full_generation | 9076.322 | +0.058% | +0.000% |
| scale10 | 6/60s | 8 | 300 | G_zero_overhead | 9076.033 | +0.061% | -0.014% |

## Extra full-lookahead oracle (different architecture)

The requested F/G predict one next Search. Here one saved generation reveals ALL distinct later Searches; this is a stronger and optimistic capability. Tool times are still charged. It is not evidence that a real model can emit the full future chain at the same cost.

| Duration | A mean s | Full lookahead, measured generation s / reduction | Full lookahead, zero generation s / reduction |
|---|---:|---:|---:|
| native | 10.543499 | 9.633489 / +8.631% | 9.004851 / +14.593% |
| scale2 | 12.693623 | 10.597953 / +16.510% | 9.734624 / +23.311% |
| scale5 | 19.143994 | 13.224747 / +30.920% | 12.226600 / +36.133% |
| scale10 | 29.894612 | 17.585977 / +41.173% | 16.569276 / +44.574% |
| fixed1 | 11.426709 | 10.083946 / +11.751% | 9.393376 / +17.795% |
| fixed2 | 14.460042 | 11.147240 / +22.910% | 10.393376 / +28.123% |
| fixed5 | 23.560042 | 14.147240 / +39.952% | 13.393376 / +43.152% |
| fixed10 | 38.726709 | 19.147240 / +50.558% | 18.393376 / +52.505% |

## Retention and duplicate suppression separated

Exact no-quota recorded-gate mean latency, evaluation30. Suppression excludes all historically requested Searches, including ordinary results which are NOT cached for reuse. It can therefore remove useful speculative caching of repeated queries. The main quota sweep explicitly compares the bundled age0/no-suppression and age1/suppression variants.

| Duration | Original, no suppression s | Original + suppression s | Extra action, no suppression s | Extra action + suppression s |
|---|---:|---:|---:|---:|
| native | 10.399114 | 10.399114 | 10.343473 | 10.371852 |
| scale2 | 12.156227 | 12.198995 | 12.142236 | 12.198995 |
| scale5 | 17.376261 | 17.376261 | 17.376261 | 17.376261 |
| scale10 | 26.110516 | 26.110516 | 26.110516 | 26.110516 |
| fixed1 | 11.163496 | 11.163496 | 11.096829 | 11.130162 |
| fixed2 | 13.496834 | 13.499077 | 13.496834 | 13.499077 |
| fixed5 | 20.596834 | 20.599077 | 20.596834 | 20.599077 |
| fixed10 | 32.430168 | 32.432410 | 32.430168 | 32.432410 |

## Perfect-predictor trigger and empty-window controls

Evaluation30, one task at a time, nonbinding quota. Isolated task resource times below include its started generation. Do not sum them to estimate a stream with answer release, because background work overlaps later tasks.

| Duration | Variant | Mean answer s | Mean isolated-task resource s |
|---|---|---:|---:|
| native | F_extended_triggers_lifetime_full_generation | 10.398902 | 10.731544 |
| native | F_original_triggers_lifetime_full_generation | 10.414092 | 10.747277 |
| native | F_reuse_triggers_empty_source_screen | 10.370637 | 10.389385 |
| native | F_reuse_triggers_full_generation | 10.370637 | 10.743502 |
| native | F_whole_episode_original_triggers_full_generation | 10.398902 | 10.731544 |
| scale2 | F_extended_triggers_lifetime_full_generation | 11.908294 | 12.006442 |
| scale2 | F_original_triggers_lifetime_full_generation | 11.908294 | 12.006442 |
| scale2 | F_reuse_triggers_empty_source_screen | 11.811440 | 11.811440 |
| scale2 | F_reuse_triggers_full_generation | 11.811440 | 12.025532 |
| scale2 | F_whole_episode_original_triggers_full_generation | 11.908294 | 12.006442 |
| scale5 | F_extended_triggers_lifetime_full_generation | 16.459991 | 16.459991 |
| scale5 | F_original_triggers_lifetime_full_generation | 16.459991 | 16.459991 |
| scale5 | F_reuse_triggers_empty_source_screen | 15.644071 | 15.644071 |
| scale5 | F_reuse_triggers_full_generation | 15.644071 | 15.754037 |
| scale5 | F_whole_episode_original_triggers_full_generation | 16.459991 | 16.459991 |
| scale10 | F_extended_triggers_lifetime_full_generation | 23.962781 | 23.962781 |
| scale10 | F_original_triggers_lifetime_full_generation | 23.962781 | 23.962781 |
| scale10 | F_reuse_triggers_empty_source_screen | 22.025005 | 22.025005 |
| scale10 | F_reuse_triggers_full_generation | 22.025005 | 22.118279 |
| scale10 | F_whole_episode_original_triggers_full_generation | 23.962781 | 23.962781 |
| fixed1 | F_extended_triggers_lifetime_full_generation | 11.143579 | 11.197663 |
| fixed1 | F_original_triggers_lifetime_full_generation | 11.159746 | 11.224470 |
| fixed1 | F_reuse_triggers_empty_source_screen | 11.109987 | 11.109987 |
| fixed1 | F_reuse_triggers_full_generation | 11.109987 | 11.284760 |
| fixed1 | F_whole_episode_original_triggers_full_generation | 11.143579 | 11.197663 |
| fixed2 | F_extended_triggers_lifetime_full_generation | 13.147890 | 13.147890 |
| fixed2 | F_original_triggers_lifetime_full_generation | 13.147890 | 13.147890 |
| fixed2 | F_reuse_triggers_empty_source_screen | 12.936635 | 12.936635 |
| fixed2 | F_reuse_triggers_full_generation | 12.936635 | 13.081856 |
| fixed2 | F_whole_episode_original_triggers_full_generation | 13.147890 | 13.147890 |
| fixed5 | F_extended_triggers_lifetime_full_generation | 18.647890 | 18.647890 |
| fixed5 | F_original_triggers_lifetime_full_generation | 18.647890 | 18.647890 |
| fixed5 | F_reuse_triggers_empty_source_screen | 18.336635 | 18.336635 |
| fixed5 | F_reuse_triggers_full_generation | 18.336635 | 18.481856 |
| fixed5 | F_whole_episode_original_triggers_full_generation | 18.647890 | 18.647890 |
| fixed10 | F_extended_triggers_lifetime_full_generation | 27.814557 | 27.814557 |
| fixed10 | F_original_triggers_lifetime_full_generation | 27.814557 | 27.814557 |
| fixed10 | F_reuse_triggers_empty_source_screen | 27.336635 | 27.336635 |
| fixed10 | F_reuse_triggers_full_generation | 27.336635 | 27.481856 |
| fixed10 | F_whole_episode_original_triggers_full_generation | 27.814557 | 27.814557 |

## Perfect candidate accuracy plus global admission

Answer release, next-Search oracle, native or synthetic 10×, three orders. These additional globally gated schedules are feasible best-found subsets, NOT exact optima. Both eager and gated columns below share the empty-source screen; main F charts charge full terminal generation instead.

| Duration | Quota | Workers | F screened eager all-work s / throughput gain | F screened + best-found pipeline gate s / gain |
|---|---|---:|---:|---:|
| native | 12/30s | 1 | 355.491552 / +0.666% | 355.491552 / +0.666% |
| native | 12/30s | 2 | 218.597516 / +0.488% | 217.899707 / +0.817% |
| native | 12/30s | 4 | 216.032147 / -0.044% | 215.026307 / +0.419% |
| native | 12/30s | 8 | 215.475840 / +0.130% | 215.475840 / +0.130% |
| native | 6/60s | 1 | 963.909690 / +0.251% | 963.909690 / +0.251% |
| native | 6/60s | 2 | 883.615788 / +2.133% | 864.937106 / +4.339% |
| native | 6/60s | 4 | 902.879075 / -0.027% | 901.790169 / +0.094% |
| native | 6/60s | 8 | 901.516418 / -0.107% | 900.546668 / +0.000% |
| scale10 | 12/30s | 1 | 660.750155 / +35.730% | 660.750155 / +35.730% |
| scale10 | 12/30s | 2 | 334.277086 / +35.319% | 334.277086 / +35.319% |
| scale10 | 12/30s | 4 | 227.673011 / +7.823% | 222.723056 / +10.204% |
| scale10 | 12/30s | 8 | 231.655330 / +1.599% | 223.667317 / +5.225% |
| scale10 | 6/60s | 1 | 983.896788 / +5.607% | 983.896788 / +5.607% |
| scale10 | 6/60s | 2 | 861.864061 / +5.388% | 858.109360 / +5.850% |
| scale10 | 6/60s | 4 | 862.232293 / +5.637% | 853.667317 / +6.694% |
| scale10 | 6/60s | 8 | 894.051351 / +2.093% | 891.708430 / +2.384% |

## Common-cache no-quota opportunity

Both ordinary required results and speculative results are cached per task. These reductions compare to the SAME common-cache baseline. E is exact per task, with original lifetime; extended E uses whole-episode retention. F retains measured generation, G sets it to zero; extra H has full future lookahead at one source generation.

| Duration | A mean s | E original s / reduction | E whole episode s / reduction | F next Search s / reduction | G next Search, zero G s / reduction | H full future, paid G s / reduction | H full future, zero G s / reduction |
|---|---:|---:|---:|---:|---:|---:|---:|
| native | 10.446185 | 10.321246 / +1.196% | 10.293984 / +1.457% | 10.292769 / +1.469% | 9.116628 / +12.728% | 9.633489 / +7.780% | 9.004851 / +13.798% |
| scale2 | 12.498994 | 12.043260 / +3.646% | 12.043260 / +3.646% | 11.754682 / +5.955% | 10.230419 / +18.150% | 10.597953 / +15.210% | 9.734624 / +22.117% |
| scale5 | 18.657422 | 17.128820 / +8.193% | 17.128820 / +8.193% | 15.644071 / +16.151% | 13.958901 / +25.183% | 13.224747 / +29.118% | 12.226600 / +34.468% |
| scale10 | 28.921468 | 25.615634 / +11.430% | 25.615634 / +11.430% | 22.025005 / +23.845% | 20.320172 / +29.740% | 17.585977 / +39.194% | 16.569276 / +42.709% |
| fixed1 | 11.326709 | 11.096829 / +2.030% | 11.063496 / +2.324% | 11.043320 / +2.502% | 9.564072 / +15.562% | 10.083946 / +10.972% | 9.393376 / +17.069% |
| fixed2 | 14.260042 | 13.428482 / +5.831% | 13.428482 / +5.831% | 12.869969 / +9.748% | 11.282761 / +20.878% | 11.147240 / +21.829% | 10.393376 / +27.115% |
| fixed5 | 23.060042 | 20.428482 / +11.412% | 20.428482 / +11.412% | 18.169969 / +21.206% | 16.553220 / +28.217% | 14.147240 / +38.650% | 13.393376 / +41.920% |
| fixed10 | 37.726709 | 32.095149 / +14.927% | 32.095149 / +14.927% | 27.003302 / +28.424% | 25.386554 / +32.709% | 19.147240 / +49.248% | 18.393376 / +51.246% |

## Cache semantics: matched native batch controls

Each row uses its own cache rule as baseline. E gates enumerate every subset. Quota shared for entire eval30 batch. F pays full terminal generation; next-Search plus reuse triggers.

| Quota | Workers | Cache | Release | Policy | Mean answer s | All answers s | All work s | Throughput gain vs same cache |
|---|---:|---|---|---|---:|---:|---:|---:|
| 10000/1s | 1 | speculative only | drain | A_none | 10.543499 | 316.304979 | 316.304979 | +0.000% |
| 10000/1s | 1 | speculative only | drain | B_ungated | 10.399114 | 321.343003 | 321.697538 | -1.676% |
| 10000/1s | 1 | speculative only | drain | D_jev_all | 10.495028 | 325.085700 | 325.440234 | -2.807% |
| 10000/1s | 1 | speculative only | drain | E_post | 10.399114 | 321.304083 | 321.658618 | -1.664% |
| 10000/1s | 1 | speculative only | drain | E_pipeline | 10.399114 | 311.973413 | 311.973413 | +1.388% |
| 10000/1s | 1 | speculative only | drain | F_full_generation | 10.370637 | 321.950526 | 322.305060 | -1.862% |
| 10000/1s | 1 | speculative only | answer | A_none | 10.543499 | 316.304979 | 316.304979 | +0.000% |
| 10000/1s | 1 | speculative only | answer | B_ungated | 10.399114 | 311.973413 | 312.327947 | +1.273% |
| 10000/1s | 1 | speculative only | answer | D_jev_all | 10.495028 | 314.850831 | 315.205365 | +0.349% |
| 10000/1s | 1 | speculative only | answer | E_post | 10.399114 | 311.973413 | 312.327947 | +1.273% |
| 10000/1s | 1 | speculative only | answer | E_pipeline | 10.399114 | 311.973413 | 311.973413 | +1.388% |
| 10000/1s | 1 | speculative only | answer | F_full_generation | 10.370637 | 311.119103 | 311.473637 | +1.551% |
| 10000/1s | 1 | common | drain | A_none | 10.446185 | 313.385548 | 313.385548 | +0.000% |
| 10000/1s | 1 | common | drain | B_ungated | 10.321246 | 319.006981 | 319.361515 | -1.871% |
| 10000/1s | 1 | common | drain | D_jev_all | 10.397713 | 322.166269 | 322.520803 | -2.832% |
| 10000/1s | 1 | common | drain | E_post | 10.321246 | 318.968061 | 319.322595 | -1.859% |
| 10000/1s | 1 | common | drain | E_pipeline | 10.321246 | 309.637391 | 309.637391 | +1.210% |
| 10000/1s | 1 | common | drain | F_full_generation | 10.292769 | 319.822022 | 320.176557 | -2.121% |
| 10000/1s | 1 | common | answer | A_none | 10.446185 | 313.385548 | 313.385548 | +0.000% |
| 10000/1s | 1 | common | answer | B_ungated | 10.321246 | 309.637391 | 309.991925 | +1.095% |
| 10000/1s | 1 | common | answer | D_jev_all | 10.397713 | 311.931400 | 312.285934 | +0.352% |
| 10000/1s | 1 | common | answer | E_post | 10.321246 | 309.637391 | 309.991925 | +1.095% |
| 10000/1s | 1 | common | answer | E_pipeline | 10.321246 | 309.637391 | 309.637391 | +1.210% |
| 10000/1s | 1 | common | answer | F_full_generation | 10.292769 | 308.783080 | 309.137615 | +1.374% |
| 12/30s | 4 | speculative only | drain | A_none | 28.185273 | 215.933327 | 215.933327 | +0.000% |
| 12/30s | 4 | speculative only | drain | B_ungated | 31.280548 | 246.261386 | 246.436532 | -12.374% |
| 12/30s | 4 | speculative only | drain | D_jev_all | 27.863150 | 215.475840 | 215.475840 | +0.211% |
| 12/30s | 4 | speculative only | drain | E_post | 27.567911 | 215.026307 | 215.026307 | +0.419% |
| 12/30s | 4 | speculative only | drain | E_pipeline | 27.872032 | 215.026307 | 215.026307 | +0.419% |
| 12/30s | 4 | speculative only | drain | F_full_generation | 27.842587 | 216.035349 | 216.210496 | -0.128% |
| 12/30s | 4 | speculative only | answer | A_none | 28.185273 | 215.933327 | 215.933327 | +0.000% |
| 12/30s | 4 | speculative only | answer | B_ungated | 31.454024 | 245.026307 | 245.026307 | -11.876% |
| 12/30s | 4 | speculative only | answer | D_jev_all | 28.210862 | 216.489633 | 216.617445 | -0.313% |
| 12/30s | 4 | speculative only | answer | E_post | 27.872032 | 215.026307 | 215.026307 | +0.419% |
| 12/30s | 4 | speculative only | answer | E_pipeline | 27.872032 | 215.026307 | 215.026307 | +0.419% |
| 12/30s | 4 | speculative only | answer | F_full_generation | 28.174109 | 216.032147 | 216.032147 | -0.044% |
| 12/30s | 4 | common | drain | A_none | 26.976830 | 214.791949 | 214.791949 | +0.000% |
| 12/30s | 4 | common | drain | B_ungated | 31.208827 | 245.046865 | 245.222011 | -12.413% |
| 12/30s | 4 | common | drain | D_jev_all | 26.659353 | 214.172630 | 214.603401 | +0.083% |
| 12/30s | 4 | common | drain | E_post | 26.651616 | 213.903845 | 214.220092 | +0.263% |
| 12/30s | 4 | common | drain | E_pipeline | 26.956186 | 214.172630 | 214.172630 | +0.284% |
| 12/30s | 4 | common | drain | F_full_generation | 26.921881 | 214.597331 | 214.772478 | +0.004% |
| 12/30s | 4 | common | answer | A_none | 26.976830 | 214.791949 | 214.791949 | +0.000% |
| 12/30s | 4 | common | answer | B_ungated | 30.811109 | 243.999771 | 243.999771 | -11.974% |
| 12/30s | 4 | common | answer | D_jev_all | 26.976830 | 214.791949 | 215.222719 | -0.201% |
| 12/30s | 4 | common | answer | E_post | 26.956186 | 214.172630 | 214.603401 | +0.083% |
| 12/30s | 4 | common | answer | E_pipeline | 26.956186 | 214.172630 | 214.172630 | +0.284% |
| 12/30s | 4 | common | answer | F_full_generation | 27.252007 | 214.597331 | 214.786495 | -0.002% |
| 6/60s | 2 | speculative only | drain | A_none | 58.260045 | 901.639520 | 901.639520 | +0.000% |
| 6/60s | 2 | speculative only | drain | B_ungated | 64.627059 | 983.883164 | 984.058311 | -8.303% |
| 6/60s | 2 | speculative only | drain | D_jev_all | 57.927645 | 901.639520 | 901.994054 | -0.039% |
| 6/60s | 2 | speculative only | drain | E_post | 56.057475 | 847.836230 | 848.011377 | +6.324% |
| 6/60s | 2 | speculative only | drain | E_pipeline | 57.021424 | 864.937106 | 864.937106 | +4.339% |
| 6/60s | 2 | speculative only | drain | F_full_generation | 56.646400 | 865.980136 | 866.155283 | +4.185% |
| 6/60s | 2 | speculative only | answer | A_none | 58.260045 | 901.639520 | 901.639520 | +0.000% |
| 6/60s | 2 | speculative only | answer | B_ungated | 64.897638 | 984.723892 | 984.899039 | -8.384% |
| 6/60s | 2 | speculative only | answer | D_jev_all | 58.260045 | 901.639520 | 901.994054 | -0.039% |
| 6/60s | 2 | speculative only | answer | E_post | 57.021424 | 864.937106 | 865.112253 | +4.317% |
| 6/60s | 2 | speculative only | answer | E_pipeline | 57.021424 | 864.937106 | 864.937106 | +4.339% |
| 6/60s | 2 | speculative only | answer | F_full_generation | 57.638880 | 883.615788 | 883.790935 | +2.113% |
| 6/60s | 2 | common | drain | A_none | 55.651181 | 845.766887 | 845.766887 | +0.000% |
| 6/60s | 2 | common | drain | B_ungated | 62.011657 | 945.178594 | 945.533128 | -10.269% |
| 6/60s | 2 | common | drain | D_jev_all | 55.340087 | 846.504647 | 846.679794 | -0.108% |
| 6/60s | 2 | common | drain | E_post | 55.328037 | 846.055113 | 846.230260 | -0.055% |
| 6/60s | 2 | common | drain | E_pipeline | 55.651181 | 845.766887 | 845.766887 | +0.000% |
| 6/60s | 2 | common | drain | F_full_generation | 55.307793 | 846.055113 | 846.230260 | -0.055% |
| 6/60s | 2 | common | answer | A_none | 55.651181 | 845.766887 | 845.766887 | +0.000% |
| 6/60s | 2 | common | answer | B_ungated | 62.326377 | 946.265748 | 946.620282 | -10.573% |
| 6/60s | 2 | common | answer | D_jev_all | 55.666166 | 846.216421 | 846.391567 | -0.074% |
| 6/60s | 2 | common | answer | E_post | 55.651181 | 845.766887 | 845.942034 | -0.021% |
| 6/60s | 2 | common | answer | E_pipeline | 55.651181 | 845.766887 | 845.766887 | +0.000% |
| 6/60s | 2 | common | answer | F_full_generation | 55.643216 | 845.766887 | 845.942034 | -0.021% |
