# Primitives with limited support

*Last generated on (YYYY-MM-DD): 2020-11-04*

We do not yet have support for `pmap` (with its collective primitives),
nor for `sharded_jit` (SPMD partitioning).

A few JAX primitives are converted to TF ops that have incomplete coverage
for data types on different kinds of devices. The most [up-to-date list of
limitations is generated automatically](#generated-summary-of-primitives-with-limited-support)
by the jax2tf coverage tests.
More detailed information can be found in the
[source code of categorize](https://github.com/google/jax/blob/master/jax/experimental/jax2tf/tests/correctness_stats.py)
for some cases.

Additionally, some primitives have numerical differences between JAX and TF in some corner cases:

  * `top_k` is implemented using `tf.math.top_k` which has limited functionality. There are
  silent errors when the array contains `inf` and `NaN` (they are sorted differently in TF vs. XLA).

  * `digamma` is converted to `tf.math.digamma` with the following limitations (all
  at the singularity points 0 and -1):
  At singularity points with dtype float32 JAX returns `NaN` and TF returns `inf`.

  * `igamma` and `igammac` are implemented using `tf.math.igamma` and `tf.math.igammac`,
  with the following limitations: At undefined points (both arguments 0 for `igamma` and
  both arguments less or equal to 0 for `igammac`) JAX returns `NaN` and TF returns 0 or
  JAX returns 1 and TF returns `NaN`.

  * `erf_inv` is converted to `tf.math.erfinv` with discrepancies at
  undefined points (< -1 or > 1): At undefined points with dtype float32 JAX
  returns `NaN` and TF returns `+inf` or `-inf`.

  * QR decomposition is implemented using `tf.linalg.qr` with
  the following limitations: QR for complex numbers will not work when using XLA
  because it is not implemented in XLA. (It works in JAX on CPU and GPU
  using custom calls to Lapack and Cusolver; it does not work in JAX on TPU.)
  It is likely that on CPU and GPU the TF version is slower than the JAX version.

  * `svd` is implemented using `tf.linalg.svd` and `tf.linalg.adjoint`:
  SVD weirdly works for bfloat16 on TPU for JAX, but fails for TF (this
  is related to a more general bfloat16 type casting problem).
  The conversion does not work for complex types because XLA does
  not implement support for complexes (once again, it works with JAX
  because the implementation there uses custom calls to cusolver).

  * `select_and_gather_add` is implemented using `XlaReduceWindow`:
  This JAX primitive is not exposed directly in the JAX API but
  arises from JVP of `lax.reduce_window` for reducers `lax.max` or
  `lax.min`. It also arises from second-order VJP of the same.

  * `select_and_scatter`: We decided to explicitly throw an error
  when trying to translate this operation. The reason is that
  the operation is not exposed in lax, and here mostly
  for completion purposes. It is not expected that this
  operation will ever have a use case.

## Updating the documentation

This file is automatically generated by running the jax2tf tests in
`jax/experimental/jax2tf/tests/primitives_test.py` and
`jax/experimental/jax2tf/tests/control_flow_ops_test.py` with the
`JAX2TF_OUTPUT_LIMITATIONS` and `JAX_ENABLE_X64` environment variables set, e.g.:

```
JAX2TF_OUTPUT_LIMITATIONS=true JAX_ENABLE_X64=true pytest --dist=no -r a --verbosity 1 jax/experimental/jax2tf/tests/primitives_test.py jax/experimental/jax2tf/tests/control_flow_ops_test.py
```

## Generated summary of primitives with limited support

The following JAX primitives are converted to Tensorflow but the result of the
conversion may trigger runtime errors when run on certain devices and with
certain data types. Note that some of these primitives have unimplemented
cases even for JAX, e.g., sort does not work for complex numbers on TPUs.
This table includes only those cases that **work** in JAX but **fail** after
conversion to Tensorflow.

| Affected primitive | Type of limitation | Description | Affected dtypes | Affected devices |
| --- | --- | --- | --- | --- |
| acosh | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| acosh | Missing TF support | Primitive is unimplemented in TF | float16 | CPU, GPU, TPU |
| add | Missing TF support | Primitive is unimplemented in TF | uint16, uint32, uint64 | CPU, GPU, TPU |
| asinh | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| asinh | Missing TF support | Primitive is unimplemented in TF | float16 | CPU, GPU, TPU |
| atan2 | Missing TF support | Primitive is unimplemented in TF | bfloat16, float16 | CPU, GPU, TPU |
| atanh | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| atanh | Missing TF support | Primitive is unimplemented in TF | float16 | CPU, GPU, TPU |
| bessel_i0e | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| bessel_i1e | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| cholesky | Missing TF support | Primitive is unimplemented in TF; this is a problem only in compiled mode (experimental_compile=True)) | complex128, complex64 | CPU, GPU, TPU |
| conv_general_dilated | Missing TF support | Primitive is unimplemented in TF; batch_group_count != 1 unsupported | ALL | CPU, GPU, TPU |
| conv_general_dilated | Missing TF support | Primitive is unimplemented in TF; likely bug in the HLO -> LLVM IR lowering of XlaConv | complex128, complex64 | CPU, GPU, TPU |
| cosh | Missing TF support | Primitive is unimplemented in TF | float16 | CPU, GPU, TPU |
| digamma | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| dot_general | Missing TF support | Primitive is unimplemented in TF | bool, int8, uint16, uint32, uint64, uint8 | CPU, GPU, TPU |
| dot_general | Missing TF support | Primitive is unimplemented in TF | int16 | TPU |
| dot_general | Missing TF support | Primitive is unimplemented in TF; only cases representable as 2D matrix multiplication can be converted properly | int16 | CPU, GPU |
| dot_general | Missing TF support | Primitive is unimplemented in TF; this is a problem only in compiled mode (experimental_compile=True)) | int64 | CPU, GPU |
| eig | Missing TF support | Primitive is unimplemented in TF; it is not possible to request both left and right eigenvectors for now | ALL | CPU, GPU, TPU |
| eig | Missing TF support | Primitive is unimplemented in TF; this is a problem only in compiled mode (experimental_compile=True)) | ALL | CPU, GPU, TPU |
| eigh | Missing TF support | Primitive is unimplemented in TF; this is a problem only in compiled mode (experimental_compile=True)) | complex128, complex64 | CPU, GPU, TPU |
| erf | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| erf_inv | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| erf_inv | Missing TF support | Primitive is unimplemented in TF | float16 | CPU, GPU, TPU |
| erfc | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| fft | Missing TF support | Primitive is unimplemented in TF; this is a problem only in compiled mode (experimental_compile=True)) | complex128, float64 | CPU, GPU, TPU |
| lgamma | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| lu | Missing TF support | Primitive is unimplemented in TF | complex64 | TPU |
| max | Missing TF support | Primitive is unimplemented in TF | bool, complex128, complex64, int8, uint16, uint32, uint64 | CPU, GPU, TPU |
| min | Missing TF support | Primitive is unimplemented in TF | bool, complex128, complex64, int8, uint16, uint32, uint64 | CPU, GPU, TPU |
| mul | Missing TF support | Primitive is unimplemented in TF | uint32, uint64 | CPU, GPU, TPU |
| nextafter | Missing TF support | Primitive is unimplemented in TF | bfloat16, float16 | CPU, GPU, TPU |
| population_count | Missing TF support | Primitive is unimplemented in TF | uint32, uint64 | CPU, GPU, TPU |
| qr | Missing TF support | Primitive is unimplemented in TF; this is a problem only in compiled mode (experimental_compile=True)) | complex128, complex64 | CPU, GPU, TPU |
| reduce_window_max | Missing TF support | Primitive is unimplemented in TF | bool, complex128, complex64, int8, uint16, uint32, uint64 | CPU, GPU, TPU |
| reduce_window_min | Missing TF support | Primitive is unimplemented in TF | bool, complex128, complex64, int8, uint16, uint32, uint64 | CPU, GPU, TPU |
| reduce_window_sum | Missing TF support | Primitive is unimplemented in TF | uint16, uint32, uint64 | CPU, GPU, TPU |
| regularized_incomplete_beta | Missing TF support | Primitive is unimplemented in TF | bfloat16, float16 | CPU, GPU, TPU |
| rem | Missing TF support | Primitive is unimplemented in TF | bfloat16, float16 | CPU, GPU, TPU |
| round | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| rsqrt | Missing TF support | Primitive is unimplemented in TF | bfloat16 | CPU, GPU |
| select_and_gather_add | Missing TF support | Primitive is unimplemented in TF | float32, float64 | TPU |
| select_and_gather_add | Missing TF support | Primitive is unimplemented in TF | float64 | CPU, GPU |
| select_and_scatter_add | Missing TF support | Primitive is unimplemented in TF | uint16, uint32, uint64 | CPU, GPU, TPU |
| sinh | Missing TF support | Primitive is unimplemented in TF | float16 | CPU, GPU, TPU |
| sort | Missing TF support | Primitive is unimplemented in TF | complex128, complex64 | CPU, GPU, TPU |
| sort | Missing TF support | Primitive is unimplemented in TF; only sorting on last dimension is supported for XlaSort | ALL | CPU, GPU, TPU |
| sort | Missing TF support | Primitive is unimplemented in TF; sorting 2 arrays where the first one is an array of booleans is not supported for XlaSort | bool | CPU, GPU, TPU |
| sort | Missing TF support | Primitive is unimplemented in TF; sorting more than 2 arrays is not supported for XlaSort | ALL | CPU, GPU, TPU |
| sort | Missing TF support | Primitive is unimplemented in TF; stable sort not implemented for XlaSort | ALL | CPU, GPU, TPU |
| svd | Missing TF support | Primitive is unimplemented in TF; this works on JAX because JAX uses a custom implementation | complex128, complex64 | CPU, GPU |
| top_k | Missing TF support | Primitive is unimplemented in TF; this is a problem only in compiled mode (experimental_compile=True)) | float64, int64, uint64 | CPU, GPU, TPU |
| triangular_solve | Missing TF support | Primitive is unimplemented in TF | bfloat16, float16 | CPU, GPU, TPU |

## Not yet implemented primitive conversions

The conversion of the following JAX primitives is not yet implemented:

`after_all`, `all_to_all`, `axis_index`, `create_token`, `igamma_grad_a`, `infeed`, `outfeed`, `pmax`, `pmin`, `ppermute`, `psum`, `random_gamma_grad`, `reduce`, `rng_uniform`, `xla_pmap`

## Primitive conversions with missing tests

The following JAX primitives have a defined conversion but are known to be
missing tests:

`argmin`, `broadcast`, `clamp`, `complex`, `conj`, `custom_lin`, `device_put`, `integer_pow`, `rev`, `select_and_scatter`, `tie_in`