# Copyright 2018 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from functools import partial
from typing import Any, Optional, Sequence, Union
import warnings

import numpy as np

from jax import lax
from jax import core
from jax import numpy as jnp
from jax._src import dtypes
from jax._src import prng
from jax.core import NamedShape
from jax._src.api import jit, vmap
from jax._src.numpy.lax_numpy import _constant_like, _convert_and_clip_integer, _check_arraylike
from jax.lib import xla_bridge
from jax.numpy.linalg import cholesky, svd, eigh
from jax.interpreters import ad
from jax.interpreters import batching
from jax.interpreters import xla
from jax._src.util import prod


Array = Any
RealArray = Array
IntegerArray = Array
# TODO: Import or define these to match
# https://github.com/numpy/numpy/blob/main/numpy/typing/_dtype_like.py.
DTypeLikeInt = Any
DTypeLikeFloat = Any

UINT_DTYPES = prng.UINT_DTYPES


### utilities


# TODO(mattjj,jakevdp): add more info to error message, use this utility more
def _asarray(x):
  """A more restrictive jnp.asarray, only accepts JAX arrays and np.ndarrays."""
  if not isinstance(x, (np.ndarray, jnp.ndarray)):
    raise TypeError(f"Function requires array input, got {x} of type {type(x)}.")
  return jnp.asarray(x)


def _random_bits(key: prng.PRNGKey, bit_width, shape) -> jnp.ndarray:
  return key.random_bits(bit_width, shape)


### key operations


def PRNGKey(seed: int) -> prng.PRNGKey:
  """Create a pseudo-random number generator (PRNG) key given an integer seed.

  Args:
    seed: a 64- or 32-bit integer used as the value of the key.

  Returns:
    A PRNG key, which is modeled as an array of shape (2,) and dtype uint32. The
    key is constructed from a 64-bit seed by effectively bit-casting to a pair
    of uint32 values (or from a 32-bit seed by first padding out with zeros).
  """
  # TODO: update doc
  return prng.make_prng_key(seed)


def fold_in(key: prng.PRNGKey, data: int) -> prng.PRNGKey:
  """Folds in data to a PRNG key to form a new PRNG key.

  Args:
    key: a PRNGKey (an array with shape (2,) and dtype uint32).
    data: a 32bit integer representing data to be folded in to the key.

  Returns:
    A new PRNGKey that is a deterministic function of the inputs and is
    statistically safe for producing a stream of new pseudo-random values.
  """
  # TODO: update doc
  return key.fold_in(jnp.uint32(data))


def split(key: prng.PRNGKey, num: int = 2) -> prng.PRNGKey:
  """Splits a PRNG key into `num` new keys by adding a leading axis.

  Args:
    key: a PRNGKey (an array with shape (2,) and dtype uint32).
    num: optional, a positive integer indicating the number of keys to produce
      (default 2).

  Returns:
    An array with shape (num, 2) and dtype uint32 representing `num` new keys.
  """
  # TODO: update doc
  return key.split(num)


### random samplers


def _check_shape(name, shape: Union[Sequence[int], NamedShape], *param_shapes):
  shape = core.as_named_shape(shape)

  if param_shapes:
    shape_ = lax.broadcast_shapes(shape.positional, *param_shapes)
    if shape.positional != shape_:
      msg = ("{} parameter shapes must be broadcast-compatible with shape "
             "argument, and the result of broadcasting the shapes must equal "
             "the shape argument, but got result {} for shape argument {}.")
      raise ValueError(msg.format(name, shape_, shape))


def uniform(key: prng.PRNGKey,
            shape: Union[Sequence[int], NamedShape] = (),
            dtype: DTypeLikeFloat = dtypes.float_,
            minval: RealArray = 0.,
            maxval: RealArray = 1.) -> jnp.ndarray:
  """Sample uniform random values in [minval, maxval) with given shape/dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).
    minval: optional, a minimum (inclusive) value broadcast-compatible with shape for the range (default 0).
    maxval: optional, a maximum (exclusive) value broadcast-compatible with shape for the range (default 1).

  Returns:
    A random array with the specified shape and dtype.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `uniform` must be a float dtype, "
                     f"got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.as_named_shape(shape)
  return _uniform(key, shape, dtype, minval, maxval)  # type: ignore

@partial(jit, static_argnums=(1, 2))
def _uniform(key, shape, dtype, minval, maxval) -> jnp.ndarray:
  _check_shape("uniform", shape)
  if not jnp.issubdtype(dtype, np.floating):
    raise TypeError("uniform only accepts floating point dtypes.")

  minval = lax.convert_element_type(minval, dtype)
  maxval = lax.convert_element_type(maxval, dtype)
  minval = lax.broadcast_to_rank(minval, shape.positional_rank)
  maxval = lax.broadcast_to_rank(maxval, shape.positional_rank)

  finfo = jnp.finfo(dtype)
  nbits, nmant = finfo.bits, finfo.nmant

  if nbits not in (16, 32, 64):
    raise TypeError("uniform only accepts 32- or 64-bit dtypes.")

  bits = _random_bits(key, nbits, shape)

  # The strategy here is to randomize only the mantissa bits with an exponent of
  # 1 (after applying the bias), then shift and scale to the desired range. The
  # bit-level transformation we use relies on Numpy and XLA having bit-for-bit
  # equivalent float representations, which might not be true on all platforms.
  float_bits = lax.bitwise_or(
      lax.shift_right_logical(bits, np.array(nbits - nmant, lax.dtype(bits))),
      np.array(1., dtype).view(UINT_DTYPES[nbits]))
  floats = lax.bitcast_convert_type(float_bits, dtype) - np.array(1., dtype)
  return lax.max(
      minval,
      lax.reshape(floats * (maxval - minval) + minval, shape.positional))


def randint(key: prng.PRNGKey,
            shape: Sequence[int],
            minval: IntegerArray,
            maxval: IntegerArray,
            dtype: DTypeLikeInt = dtypes.int_):
  """Sample uniform random values in [minval, maxval) with given shape/dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: a tuple of nonnegative integers representing the shape.
    minval: int or array of ints broadcast-compatible with ``shape``, a minimum
      (inclusive) value for the range.
    maxval: int or array of ints broadcast-compatible with ``shape``, a maximum
      (exclusive) value for the range.
    dtype: optional, an int dtype for the returned values (default int64 if
      jax_enable_x64 is true, otherwise int32).

  Returns:
    A random array with the specified shape and dtype.
  """
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _randint(key, shape, minval, maxval, dtype)

@partial(jit, static_argnums=(1, 4))
def _randint(key, shape, minval, maxval, dtype):
  _check_shape("randint", shape, np.shape(minval), np.shape(maxval))
  if not jnp.issubdtype(dtype, np.integer):
    raise TypeError(f"randint only accepts integer dtypes, got {dtype}")

  _check_arraylike("randint", minval, maxval)
  minval = jnp.asarray(minval)
  maxval = jnp.asarray(maxval)
  if not jnp.issubdtype(minval.dtype, np.integer):
    minval = minval.astype(int)
  if not jnp.issubdtype(maxval.dtype, np.integer):
    maxval = maxval.astype(int)

  # Flag where maxval is greater than the maximum value of dtype
  # in order to handle cases like randint(key, shape, 0, 256, 'uint8')
  maxval_out_of_range = lax.gt(
    maxval, _convert_and_clip_integer(jnp.array(jnp.iinfo(dtype).max, dtype), maxval.dtype))

  minval = _convert_and_clip_integer(minval, dtype)
  maxval = _convert_and_clip_integer(maxval, dtype)
  minval = lax.broadcast_to_rank(minval, len(shape))
  maxval = lax.broadcast_to_rank(maxval, len(shape))
  nbits = jnp.iinfo(dtype).bits

  if nbits not in (8, 16, 32, 64):
    raise TypeError(f"randint only accepts 8-, 16-, 32-, or 64-bit dtypes, got {dtype}")

  # This algorithm is biased whenever (maxval - minval) is not a power of 2.
  # We generate double the number of random bits required by the dtype so as to
  # reduce that bias.
  k1, k2 = split(key)
  rbits = lambda key: _random_bits(key, nbits, shape)
  higher_bits, lower_bits = rbits(k1), rbits(k2)

  unsigned_dtype = UINT_DTYPES[nbits]
  span = lax.convert_element_type(maxval - minval, unsigned_dtype)

  # Ensure that span=1 when maxval <= minval, so minval is always returned;
  # https://github.com/google/jax/issues/222
  span = lax.select(maxval <= minval, lax.full_like(span, 1), span)

  # When maxval is out of range, the span has to be one larger.
  # If span is already the maximum representable value, this will wrap to zero,
  # causing remainders below to have no effect, which is the correct semantics.
  span = lax.select(
    maxval_out_of_range & (maxval > minval),
    lax.add(span, lax._const(span, 1)),
    span)

  # To compute a remainder operation on an integer that might have twice as many
  # bits as we can represent in the native unsigned dtype, we compute a
  # multiplier equal to 2**nbits % span. To avoid overflow, we use the identity:
  #  (a * b) % N = [(a % N) * (b % N)] % N
  multiplier = lax.rem(lax._const(span, 2 ** (nbits // 2)), span)
  multiplier = lax.rem(lax.mul(multiplier, multiplier), span)

  random_offset = lax.add(lax.mul(lax.rem(higher_bits, span), multiplier),
                          lax.rem(lower_bits, span))
  random_offset = lax.rem(random_offset, span)
  return lax.add(minval, lax.convert_element_type(random_offset, dtype))


def shuffle(key: prng.PRNGKey, x: Array, axis: int = 0) -> jnp.ndarray:
  """Shuffle the elements of an array uniformly at random along an axis.

  Args:
    key: a PRNGKey used as the random key.
    x: the array to be shuffled.
    axis: optional, an int axis along which to shuffle (default 0).

  Returns:
    A shuffled version of x.
  """
  msg = ("jax.random.shuffle is deprecated and will be removed in a future release. "
         "Use jax.random.permutation")
  warnings.warn(msg, FutureWarning)
  return _shuffle(key, x, axis)  # type: ignore


def permutation(key: prng.PRNGKey, x: Array) -> jnp.ndarray:
  """
  Permute elements of an array along its first axis or return a permuted range.

  If `x` is a multi-dimensional array, it is only shuffled along its
  first index.

  Args:n
    key: a PRNGKey used as the random key.
    x: the array or integer range to be shuffled.

  Returns:
    A shuffled version of x or array range
  """
  if not np.ndim(x):
    # scalar case, must be a concrete integer
    if not np.issubdtype(lax.dtype(x), np.integer):
      raise TypeError("x must be an integer or at least 1-dimensional")
    x = int(x)  # type: ignore[assignment]
    return _shuffle(key, jnp.arange(x), 0)
  elif np.ndim(x) == 1:
    return _shuffle(key, x, 0)
  else:
    assert isinstance(x, jnp.ndarray)
    ind = _shuffle(key, jnp.arange(x.shape[0]), 0)  # type: ignore[attribute-error]
    return x[ind]


@partial(jit, static_argnums=(2,))
def _shuffle(key, x, axis) -> jnp.ndarray:
  # On parallel architectures, Fisher-Yates is more expensive than doing
  # multiple sorts. This algorithm is based on one developed and analyzed by
  # tjablin@. We sort according to randomly-generated 32bit keys, but those keys
  # may have collisions. If we repeat the process, using fresh 32bit keys for
  # each sort, then whenever all pairs of elements have been assigned distinct
  # keys at some iteration (or equivalently when the strings formed by
  # concatenating the successive keys for each element are all distinct) then we
  # are guaranteed to have a perfect sample (assuming that either the sort is
  # stable or that any bias is not value-dependent). Since checking uniqueness
  # at runtime may be expensive, we use a heuristic static stop criterion
  # developed by tjablin@. See tensorflow/compiler/tf2xla/random_ops.cc for more
  # info, and for the original implementation of this algorithm. See also
  # Section 2 of http://people.csail.mit.edu/costis/6896sp11/lec5s.pdf for
  # another analysis (where the keys are generated one bit at a time).
  exponent = 3  # see tjablin@'s analysis for explanation of this parameter
  uint32max = jnp.iinfo(np.uint32).max
  num_rounds = int(np.ceil(exponent * np.log(max(1, x.size)) / np.log(uint32max)))

  for _ in range(num_rounds):
    key, subkey = split(key)
    sort_keys = _random_bits(subkey, 32, x.shape)
    _, x = lax.sort_key_val(sort_keys, x, axis)

  return x


def choice(key: prng.PRNGKey,
           a: IntegerArray,
           shape: Sequence[int] = (),
           replace: bool = True,
           p=None) -> jnp.ndarray:
  """Generates a random sample from a given 1-D array.

  Args:
    key: a PRNGKey used as the random key.
    a : 1D array or int. If an ndarray, a random sample is generated from
      its elements. If an int, the random sample is generated as if a were
      arange(a).
    shape : tuple of ints, optional. Output shape.  If the given shape is,
      e.g., ``(m, n)``, then ``m * n`` samples are drawn.  Default is (),
      in which case a single value is returned.
    replace : boolean.  Whether the sample is with or without replacement.
      default is True.
    p : 1-D array-like, The probabilities associated with each entry in a.
      If not given the sample assumes a uniform distribution over all
      entries in a.

  Returns:
    An array of shape `shape` containing samples from `a`.
  """
  if not isinstance(shape, Sequence):
    raise TypeError("shape argument of jax.random.choice must be a sequence, "
                    f"got {shape}")
  if np.ndim(a) not in [0, 1]:
    raise ValueError("a must be an integer or 1-dimensional")
  _check_arraylike("choice", a)
  if np.ndim(a) == 0:
    a = core.concrete_or_error(int, a, "The error occurred in jax.random.choice()")
  else:
    a = jnp.asarray(a)
  n_inputs = int(a) if np.ndim(a) == 0 else len(a)  # type: ignore[arg-type]
  n_draws = prod(shape)
  if n_draws == 0:
    return jnp.zeros(shape, dtype=lax.dtype(a))
  if n_inputs <= 0:
    raise ValueError("a must be greater than 0 unless no samples are taken")
  if not replace and n_draws > n_inputs:
    raise ValueError("Cannot take a larger sample than population when 'replace=False'")

  if p is None:
    if replace:
      ind = randint(key, shape, 0, n_inputs)
      result = ind if np.ndim(a) == 0 else a[ind]  # type: ignore[index]
    else:
      result = permutation(key, a)[:n_draws]
  else:
    if p.shape != (n_inputs,):
      raise ValueError("p must be None or match the shape of a")
    if replace:
      p_cuml = jnp.cumsum(p)
      r = p_cuml[-1] * (1 - uniform(key, shape))
      ind = jnp.searchsorted(p_cuml, r)
      result = ind if np.ndim(a) == 0 else a[ind]  # type: ignore[index]
    else:
      # Gumbel top-k trick: https://timvieira.github.io/blog/post/2019/09/16/algorithms-for-sampling-without-replacement/
      g = -gumbel(key, (n_inputs,)) - jnp.log(p)
      ind = jnp.argsort(g)[:n_draws]
      result = ind if np.ndim(a) == 0 else a[ind]  # type: ignore[index]
  return result.reshape(shape)


def normal(key: prng.PRNGKey,
           shape: Union[Sequence[int], NamedShape] = (),
           dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample standard normal random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified shape and dtype.
  """
  if not dtypes.issubdtype(dtype, np.inexact):
    raise ValueError(f"dtype argument to `normal` must be a float or complex dtype, "
                     f"got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.as_named_shape(shape)
  return _normal(key, shape, dtype)  # type: ignore

@partial(jit, static_argnums=(1, 2))
def _normal(key, shape, dtype) -> jnp.ndarray:
  if dtypes.issubdtype(dtype, np.complexfloating):
    sqrt2 = np.array(np.sqrt(2), dtype)

    key_re, key_im = split(key)
    real_dtype = np.array(0, dtype).real.dtype
    _re = _normal_real(key_re, shape, real_dtype)
    _im = _normal_real(key_im, shape, real_dtype)
    return (_re + 1j * _im) / sqrt2
  else:
    return _normal_real(key, shape, dtype) # type: ignore

@partial(jit, static_argnums=(1, 2))
def _normal_real(key, shape, dtype) -> jnp.ndarray:
  _check_shape("normal", shape)
  lo = np.nextafter(np.array(-1., dtype), np.array(0., dtype), dtype=dtype)
  hi = np.array(1., dtype)
  u = uniform(key, shape, dtype, lo, hi)  # type: ignore[arg-type]
  return np.array(np.sqrt(2), dtype) * lax.erf_inv(u)


def multivariate_normal(key: prng.PRNGKey,
                        mean: RealArray,
                        cov: RealArray,
                        shape: Optional[Sequence[int]] = None,
                        dtype: DTypeLikeFloat = dtypes.float_,
                        method: str = 'cholesky') -> jnp.ndarray:
  """Sample multivariate normal random values with given mean and covariance.

  Args:
    key: a PRNGKey used as the random key.
    mean: a mean vector of shape ``(..., n)``.
    cov: a positive definite covariance matrix of shape ``(..., n, n)``. The
      batch shape ``...`` must be broadcast-compatible with that of ``mean``.
    shape: optional, a tuple of nonnegative integers specifying the result
      batch shape; that is, the prefix of the result shape excluding the last
      axis. Must be broadcast-compatible with ``mean.shape[:-1]`` and
      ``cov.shape[:-2]``. The default (None) produces a result batch shape by
      broadcasting together the batch shapes of ``mean`` and ``cov``.
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).
    method: optional, a method to compute the factor of ``cov``.
      Must be one of 'svd', eigh, and 'cholesky'. Default 'cholesky'.
  Returns:
    A random array with the specified dtype and shape given by
    ``shape + mean.shape[-1:]`` if ``shape`` is not None, or else
    ``broadcast_shapes(mean.shape[:-1], cov.shape[:-2]) + mean.shape[-1:]``.
  """
  if method not in {'svd', 'eigh', 'cholesky'}:
    raise ValueError("method must be one of {'svd', 'eigh', 'cholesky'}")
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `multivariate_normal` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  if shape is not None:
    shape = core.canonicalize_shape(shape)
  return _multivariate_normal(key, mean, cov, shape, dtype, method)  # type: ignore

@partial(jit, static_argnums=(3, 4, 5))
def _multivariate_normal(key, mean, cov, shape, dtype, method) -> jnp.ndarray:
  if not np.ndim(mean) >= 1:
    msg = "multivariate_normal requires mean.ndim >= 1, got mean.ndim == {}"
    raise ValueError(msg.format(np.ndim(mean)))
  if not np.ndim(cov) >= 2:
    msg = "multivariate_normal requires cov.ndim >= 2, got cov.ndim == {}"
    raise ValueError(msg.format(np.ndim(cov)))
  n = mean.shape[-1]
  if np.shape(cov)[-2:] != (n, n):
    msg = ("multivariate_normal requires cov.shape == (..., n, n) for n={n}, "
           "but got cov.shape == {shape}.")
    raise ValueError(msg.format(n=n, shape=np.shape(cov)))

  if shape is None:
    shape = lax.broadcast_shapes(mean.shape[:-1], cov.shape[:-2])
  else:
    _check_shape("normal", shape, mean.shape[:-1], cov.shape[:-2])

  if method == 'svd':
    (u, s, _) = svd(cov)
    factor = u * jnp.sqrt(s)
  elif method == 'eigh':
    (w, v) = eigh(cov)
    factor = v * jnp.sqrt(w)
  else: # 'cholesky'
    factor = cholesky(cov)
  normal_samples = normal(key, shape + mean.shape[-1:], dtype)
  return mean + jnp.einsum('...ij,...j->...i', factor, normal_samples)


def truncated_normal(key: prng.PRNGKey,
                     lower: RealArray,
                     upper: RealArray,
                     shape: Optional[Union[Sequence[int], NamedShape]] = None,
                     dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample truncated standard normal random values with given shape and dtype.

  Args:
    key: a PRNGKey used as the random key.
    lower: a float or array of floats representing the lower bound for
      truncation. Must be broadcast-compatible with ``upper``.
    upper: a float or array of floats representing the  upper bound for
      truncation. Must be broadcast-compatible with ``lower``.
    shape: optional, a tuple of nonnegative integers specifying the result
      shape. Must be broadcast-compatible with ``lower`` and ``upper``. The
      default (None) produces a result shape by broadcasting ``lower`` and
      ``upper``.
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified dtype and shape given by ``shape`` if
    ``shape`` is not None, or else by broadcasting ``lower`` and ``upper``.
    Returns values in the open interval ``(lower, upper)``.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `truncated_normal` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  if shape is not None:
    shape = core.as_named_shape(shape)
  return _truncated_normal(key, lower, upper, shape, dtype)  # type: ignore

@partial(jit, static_argnums=(3, 4))
def _truncated_normal(key, lower, upper, shape, dtype) -> jnp.ndarray:
  if shape is None:
    shape = lax.broadcast_shapes(np.shape(lower), np.shape(upper))
  else:
    _check_shape("truncated_normal", shape, np.shape(lower), np.shape(upper))

  sqrt2 = np.array(np.sqrt(2), dtype)
  lower = lax.convert_element_type(lower, dtype)
  upper = lax.convert_element_type(upper, dtype)
  a = lax.erf(lower / sqrt2)
  b = lax.erf(upper / sqrt2)
  if not jnp.issubdtype(dtype, np.floating):
    raise TypeError("truncated_normal only accepts floating point dtypes.")
  u = uniform(key, shape, dtype, minval=a, maxval=b)
  out = sqrt2 * lax.erf_inv(u)
  # Clamp the value to the open interval (lower, upper) to make sure that
  # rounding (or if we chose `a` for `u`) doesn't push us outside of the range.
  return jnp.clip(
      out,
      lax.nextafter(lax.stop_gradient(lower), np.array(np.inf, dtype=dtype)),
      lax.nextafter(lax.stop_gradient(upper), np.array(-np.inf, dtype=dtype)))


def bernoulli(key: prng.PRNGKey,
              p: RealArray = np.float32(0.5),
              shape: Optional[Union[Sequence[int], NamedShape]] = None) -> jnp.ndarray:
  """Sample Bernoulli random values with given shape and mean.

  Args:
    key: a PRNGKey used as the random key.
    p: optional, a float or array of floats for the mean of the random
      variables. Must be broadcast-compatible with ``shape``. Default 0.5.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Must be broadcast-compatible with ``p.shape``. The default (None)
      produces a result shape equal to ``p.shape``.

  Returns:
    A random array with boolean dtype and shape given by ``shape`` if ``shape``
    is not None, or else ``p.shape``.
  """
  dtype = dtypes.canonicalize_dtype(lax.dtype(p))
  if shape is not None:
    shape = core.as_named_shape(shape)
  if not jnp.issubdtype(dtype, np.floating):
    msg = "bernoulli probability `p` must have a floating dtype, got {}."
    raise TypeError(msg.format(dtype))
  p = lax.convert_element_type(p, dtype)
  return _bernoulli(key, p, shape)  # type: ignore

@partial(jit, static_argnums=(2,))
def _bernoulli(key, p, shape) -> jnp.ndarray:
  if shape is None:
    # TODO: Use the named part of `p` as well
    shape = np.shape(p)
  else:
    _check_shape("bernoulli", shape, np.shape(p))

  return uniform(key, shape, lax.dtype(p)) < p


def beta(key: prng.PRNGKey,
         a: RealArray,
         b: RealArray,
         shape: Optional[Sequence[int]] = None,
         dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Beta random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    a: a float or array of floats broadcast-compatible with ``shape``
      representing the first parameter "alpha".
    b: a float or array of floats broadcast-compatible with ``shape``
      representing the second parameter "beta".
    shape: optional, a tuple of nonnegative integers specifying the result
      shape. Must be broadcast-compatible with ``a`` and ``b``. The default
      (None) produces a result shape by broadcasting ``a`` and ``b``.
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified dtype and shape given by ``shape`` if
    ``shape`` is not None, or else by broadcasting ``a`` and ``b``.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `beta` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  if shape is not None:
    shape = core.canonicalize_shape(shape)
  return _beta(key, a, b, shape, dtype)

def _beta(key, a, b, shape, dtype):
  if shape is None:
    shape = lax.broadcast_shapes(np.shape(a), np.shape(b))
  else:
    _check_shape("beta", shape, np.shape(a), np.shape(b))

  a = lax.convert_element_type(a, dtype)
  b = lax.convert_element_type(b, dtype)
  key_a, key_b = split(key)
  a = jnp.broadcast_to(a, shape)
  b = jnp.broadcast_to(b, shape)
  gamma_a = gamma(key_a, a, shape, dtype)
  gamma_b = gamma(key_b, b, shape, dtype)
  return gamma_a / (gamma_a + gamma_b)


def cauchy(key: prng.PRNGKey,
           shape: Sequence[int] = (),
           dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Cauchy random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified shape and dtype.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `cauchy` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _cauchy(key, shape, dtype)

@partial(jit, static_argnums=(1, 2))
def _cauchy(key, shape, dtype):
  _check_shape("cauchy", shape)
  u = uniform(key, shape, dtype, minval=jnp.finfo(dtype).eps, maxval=1.)
  pi = _constant_like(u, np.pi)
  return lax.tan(lax.mul(pi, lax.sub(u, _constant_like(u, 0.5))))


def dirichlet(key: prng.PRNGKey,
              alpha: RealArray,
              shape: Optional[Sequence[int]] = None,
              dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Dirichlet random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    alpha: an array of shape ``(..., n)`` used as the concentration
      parameter of the random variables.
    shape: optional, a tuple of nonnegative integers specifying the result
      batch shape; that is, the prefix of the result shape excluding the last
      element of value ``n``. Must be broadcast-compatible with
      ``alpha.shape[:-1]``. The default (None) produces a result shape equal to
      ``alpha.shape``.
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified dtype and shape given by
    ``shape + (alpha.shape[-1],)`` if ``shape`` is not None, or else
    ``alpha.shape``.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `dirichlet` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  if shape is not None:
    shape = core.canonicalize_shape(shape)
  return _dirichlet(key, alpha, shape, dtype)

@partial(jit, static_argnums=(2, 3))
def _dirichlet(key, alpha, shape, dtype):
  if not np.ndim(alpha) >= 1:
    msg = "dirichlet requires alpha.ndim >= 1, got alpha.ndim == {}"
    raise ValueError(msg.format(np.ndim(alpha)))

  if shape is None:
    shape = np.shape(alpha)[:-1]
  else:
    _check_shape("dirichlet", shape, np.shape(alpha)[:-1])

  alpha = lax.convert_element_type(alpha, dtype)
  gamma_samples = gamma(key, alpha, shape + np.shape(alpha)[-1:], dtype)
  return gamma_samples / jnp.sum(gamma_samples, axis=-1, keepdims=True)


def exponential(key: prng.PRNGKey,
                shape: Sequence[int] = (),
                dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Exponential random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified shape and dtype.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `exponential` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _exponential(key, shape, dtype)

@partial(jit, static_argnums=(1, 2))
def _exponential(key, shape, dtype):
  _check_shape("exponential", shape)
  u = uniform(key, shape, dtype)
  # taking 1 - u to move the domain of log to (0, 1] instead of [0, 1)
  return lax.neg(lax.log1p(lax.neg(u)))


def _gamma_one(key, alpha):
  # Ref: A simple method for generating gamma variables, George Marsaglia and Wai Wan Tsang
  # The algorithm can also be founded in:
  # https://en.wikipedia.org/wiki/Gamma_distribution#Generating_gamma-distributed_random_variables
  zero = _constant_like(alpha, 0)
  one = _constant_like(alpha, 1)
  minus_one = _constant_like(alpha, -1)
  one_over_two = _constant_like(alpha, 0.5)
  one_over_three = _constant_like(alpha, 1. / 3.)
  squeeze_const = _constant_like(alpha, 0.0331)
  dtype = lax.dtype(alpha)

  key, subkey = split(key)
  # for alpha < 1, we boost alpha to alpha + 1 and get a sample according to
  # Gamma(alpha) ~ Gamma(alpha+1) * Uniform()^(1 / alpha)
  boost = lax.select(lax.ge(alpha, one),
                     one,
                     lax.pow(uniform(subkey, (), dtype=dtype), lax.div(one, alpha)))
  alpha = lax.select(lax.ge(alpha, one), alpha, lax.add(alpha, one))

  d = lax.sub(alpha, one_over_three)
  c = lax.div(one_over_three, lax.sqrt(d))

  def _cond_fn(kXVU):
    _, X, V, U = kXVU
    # TODO: use lax.cond when its batching rule is supported
    # The reason is to avoid evaluating second condition which involves log+log
    # if the first condition is satisfied
    cond = lax.bitwise_and(lax.ge(U, lax.sub(one, lax.mul(squeeze_const, lax.mul(X, X)))),
                           lax.ge(lax.log(U), lax.add(lax.mul(X, one_over_two),
                                                      lax.mul(d, lax.add(lax.sub(one, V),
                                                                         lax.log(V))))))
    return cond

  def _body_fn(kXVU):
    def _next_kxv(kxv):
      key = kxv[0]
      key, subkey = split(key)
      x = normal(subkey, (), dtype=dtype)
      v = lax.add(one, lax.mul(x, c))
      return key, x, v

    key = kXVU[0]
    key, x_key, U_key = split(key, 3)
    _, x, v = lax.while_loop(lambda kxv: lax.le(kxv[2], zero), _next_kxv, (x_key, zero, minus_one))
    X = lax.mul(x, x)
    V = lax.mul(lax.mul(v, v), v)
    U = uniform(U_key, (), dtype=dtype)
    return key, X, V, U

  # initial state is chosen such that _cond_fn will return True
  _, _, V, _ = lax.while_loop(_cond_fn, _body_fn, (key, zero, one, _constant_like(alpha, 2)))
  z = lax.mul(lax.mul(d, V), boost)
  return lax.select(lax.eq(z, zero), jnp.finfo(z.dtype).tiny, z)


def _gamma_grad(sample, a):
  samples = jnp.reshape(sample, -1)
  alphas = jnp.reshape(a, -1)
  if xla_bridge.get_backend().platform == 'cpu':
    grads = lax.map(lambda args: lax.random_gamma_grad(*args), (alphas, samples))
  else:
    grads = vmap(lax.random_gamma_grad)(alphas, samples)
  return grads.reshape(np.shape(a))

def _gamma_impl(key, a, use_vmap=False):
  a_shape = jnp.shape(a)
  # split key to match the shape of a
  key_ndim = jnp.ndim(key) - 1
  key = prng.PRNGKey(jnp.reshape(key, (-1, 2)))
  key = vmap(split, in_axes=(0, None))(key, prod(a_shape[key_ndim:]))
  keys = prng.PRNGKey(jnp.reshape(key.key, (-1, 2)))
  alphas = jnp.reshape(a, -1)
  if use_vmap:
    samples = vmap(_gamma_one)(keys, alphas)
  else:
    samples = lax.map(lambda args: _gamma_one(*args), (keys, alphas))

  return jnp.reshape(samples, a_shape)

def _gamma_batching_rule(batched_args, batch_dims):
    k, a = batched_args
    bk, ba = batch_dims
    size = next(t.shape[i] for t, i in zip(batched_args, batch_dims) if i is not None)
    k = batching.bdim_at_front(k, bk, size)
    a = batching.bdim_at_front(a, ba, size)
    return random_gamma_p.bind(k, a), 0

random_gamma_p = core.Primitive('random_gamma')
random_gamma_p.def_impl(_gamma_impl)
random_gamma_p.def_abstract_eval(lambda key, a: core.raise_to_shaped(a))
ad.defjvp2(random_gamma_p, None, lambda tangent, ans, key, a: tangent * _gamma_grad(ans, a))
xla.translations_with_avals[random_gamma_p] = xla.lower_fun(
    partial(_gamma_impl, use_vmap=True),
    multiple_results=False, with_avals=True)
xla.backend_specific_translations['cpu'][random_gamma_p] = xla.lower_fun(
    partial(_gamma_impl, use_vmap=False),
    multiple_results=False)
batching.primitive_batchers[random_gamma_p] = _gamma_batching_rule

def gamma(key: prng.PRNGKey,
          a: RealArray,
          shape: Optional[Sequence[int]] = None,
          dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Gamma random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    a: a float or array of floats broadcast-compatible with ``shape``
      representing the parameter of the distribution.
    shape: optional, a tuple of nonnegative integers specifying the result
      shape. Must be broadcast-compatible with ``a``. The default (None)
      produces a result shape equal to ``a.shape``.
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified dtype and with shape given by ``shape`` if
    ``shape`` is not None, or else by ``a.shape``.
  """
  if not isinstance(key, prng.PRNGKey):
    raise NotImplementedError(
        f'`gamma` only supported for the default PRNG, not f{type(key)}')
  return gamma_threefry2x32(key.key, a, shape, dtype)

def gamma_threefry2x32(key: jnp.ndarray,  # raw ndarray form of a 2x32 key
                       a: RealArray,
                       shape: Optional[Sequence[int]] = None,
                       dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `gamma` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  if shape is not None:
    shape = core.canonicalize_shape(shape)
  return _gamma(key, a, shape, dtype)

@partial(jit, static_argnums=(2, 3))
def _gamma(key, a, shape, dtype):
  if shape is None:
    shape = np.shape(a)
  else:
    _check_shape("gamma", shape, np.shape(a))

  a = lax.convert_element_type(a, dtype)
  if np.shape(a) != shape:
    a = jnp.broadcast_to(a, shape)
  return random_gamma_p.bind(key, a)


@partial(jit, static_argnums=(2, 3, 4))
def _poisson_knuth(key, lam, shape, dtype, max_iters):
  # Knuth's algorithm for generating Poisson random variates.
  # Reference:
  # https://en.wikipedia.org/wiki/Poisson_distribution#Generating_Poisson-distributed_random_variables

  def body_fn(carry):
    i, k, rng, log_prod = carry
    rng, subkey = split(rng)
    k = lax.select(log_prod > -lam, k + 1, k)
    u = uniform(subkey, shape, np.float32)
    return i + 1, k, rng, log_prod + jnp.log(u)

  def cond_fn(carry):
    i, log_prod = carry[0], carry[3]
    return (log_prod > -lam).any() & (i < max_iters)

  k_init = lax.full_like(lam, 0, dtype, shape)
  log_rate_init = lax.full_like(lam, 0, np.float32, shape)
  k = lax.while_loop(cond_fn, body_fn, (0, k_init, key, log_rate_init))[1]
  return (k - 1).astype(dtype)


@partial(jit, static_argnums=(2, 3, 4))
def _poisson_rejection(key, lam, shape, dtype, max_iters):
  # Transformed rejection due to Hormann.
  # Reference:
  # http://citeseer.ist.psu.edu/viewdoc/citations;jsessionid=1BEB35946CC807879F55D42512E5490C?doi=10.1.1.48.3054.
  log_lam = lax.log(lam)
  b = 0.931 + 2.53 * lax.sqrt(lam)
  a = -0.059 + 0.02483 * b
  inv_alpha = 1.1239 + 1.1328 / (b - 3.4)
  v_r = 0.9277 - 3.6224 / (b - 2)

  def body_fn(carry):
    i, k_out, accepted, key = carry
    key, subkey_0, subkey_1 = split(key, 3)

    u = uniform(subkey_0, shape, lam.dtype) - 0.5
    v = uniform(subkey_1, shape, lam.dtype)
    u_shifted = 0.5 - abs(u)

    k = lax.floor((2 * a / u_shifted + b) * u + lam + 0.43)
    s = lax.log(v * inv_alpha / (a / (u_shifted * u_shifted) + b))
    t = -lam + k * log_lam - lax.lgamma(k + 1)

    accept1 = (u_shifted >= 0.07) & (v <= v_r)
    reject = (k < 0) | ((u_shifted < 0.013) & (v > u_shifted))
    accept2 = s <= t
    accept = accept1 | (~reject & accept2)

    k_out = lax.select(accept, k, k_out)
    accepted |= accept

    return i + 1, k_out, accepted, key

  def cond_fn(carry):
    i, k_out, accepted, key = carry
    return (~accepted).any() & (i < max_iters)

  k_init = lax.full_like(lam, -1, lam.dtype, shape)
  accepted = lax.full_like(lam, False, jnp.bool_, shape)
  k = lax.while_loop(cond_fn, body_fn, (0, k_init, accepted, key))[1]
  return k.astype(dtype)


@partial(jit, static_argnums=(2, 3))
def _poisson(key, lam, shape, dtype):
  # The implementation matches TensorFlow and NumPy:
  # https://github.com/tensorflow/tensorflow/blob/v2.2.0-rc3/tensorflow/core/kernels/random_poisson_op.cc
  # https://github.com/numpy/numpy/blob/v1.18.3/numpy/random/src/distributions/distributions.c#L574
  # For lambda < 10, we use the Knuth algorithm; otherwise, we use transformed
  # rejection sampling.
  use_knuth = lam < 10
  lam_knuth = lax.select(use_knuth, lam, lax.full_like(lam, 0.0))
  # The acceptance probability for rejection sampling maxes out at 89% as
  # λ -> ∞, so pick some arbitrary large value.
  lam_rejection = lax.select(use_knuth, lax.full_like(lam, 1e5), lam)
  max_iters = dtype.type(jnp.iinfo(dtype).max)  # insanely conservative
  result = lax.select(
    use_knuth,
    _poisson_knuth(key, lam_knuth, shape, dtype, max_iters),
    _poisson_rejection(key, lam_rejection, shape, dtype, max_iters),
  )
  return lax.select(lam == 0, jnp.zeros_like(result), result)


def poisson(key: prng.PRNGKey,
            lam: RealArray,
            shape: Sequence[int] = (),
            dtype: DTypeLikeInt = dtypes.int_) -> jnp.ndarray:
  """Sample Poisson random values with given shape and integer dtype.

  Args:
    key: a PRNGKey used as the random key.
    lam: rate parameter (mean of the distribution), must be >= 0.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a integer dtype for the returned values (default int64 if
      jax_enable_x64 is true, otherwise int32).

  Returns:
    A random array with the specified shape and dtype.
  """
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  if np.shape(lam) != shape:
    lam = jnp.broadcast_to(lam, shape)
  lam = lax.convert_element_type(lam, np.float32)
  return _poisson(key, lam, shape, dtype)


def gumbel(key: prng.PRNGKey,
           shape: Sequence[int] = (),
           dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Gumbel random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified shape and dtype.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `gumbel` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _gumbel(key, shape, dtype)

@partial(jit, static_argnums=(1, 2))
def _gumbel(key, shape, dtype):
  _check_shape("gumbel", shape)
  return -jnp.log(-jnp.log(
      uniform(key, shape, dtype, minval=jnp.finfo(dtype).tiny, maxval=1.)))


def categorical(key: prng.PRNGKey,
                logits: RealArray,
                axis: int = -1,
                shape: Optional[Sequence[int]] = None) -> jnp.ndarray:
  """Sample random values from categorical distributions.

  Args:
    key: a PRNGKey used as the random key.
    logits: Unnormalized log probabilities of the categorical distribution(s) to sample from,
      so that `softmax(logits, axis)` gives the corresponding probabilities.
    axis: Axis along which logits belong to the same categorical distribution.
    shape: Optional, a tuple of nonnegative integers representing the result shape.
      Must be broadcast-compatible with ``np.delete(logits.shape, axis)``.
      The default (None) produces a result shape equal to ``np.delete(logits.shape, axis)``.

  Returns:
    A random array with int dtype and shape given by ``shape`` if ``shape``
    is not None, or else ``np.delete(logits.shape, axis)``.
  """

  if axis >= 0:
    axis -= len(logits.shape)

  batch_shape = tuple(np.delete(logits.shape, axis))
  if shape is None:
    shape = batch_shape
  else:
    shape = tuple(shape)
    _check_shape("categorical", shape, batch_shape)

  sample_shape = shape[:len(shape)-len(batch_shape)]
  return jnp.argmax(gumbel(key, sample_shape + logits.shape, logits.dtype) + logits, axis=axis)


def laplace(key: prng.PRNGKey,
            shape: Sequence[int] = (),
            dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Laplace random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified shape and dtype.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `laplace` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _laplace(key, shape, dtype)

@partial(jit, static_argnums=(1, 2))
def _laplace(key, shape, dtype):
  _check_shape("laplace", shape)
  u = uniform(
      key, shape, dtype, minval=-1. + jnp.finfo(dtype).epsneg, maxval=1.)
  return lax.mul(lax.sign(u), lax.log1p(lax.neg(lax.abs(u))))


def logistic(key: prng.PRNGKey,
             shape: Sequence[int] = (),
             dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample logistic random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    shape: optional, a tuple of nonnegative integers representing the result
      shape. Default ().
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified shape and dtype.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `logistic` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _logistic(key, shape, dtype)

@partial(jit, static_argnums=(1, 2))
def _logistic(key, shape, dtype):
  _check_shape("logistic", shape)
  x = uniform(key, shape, dtype, minval=jnp.finfo(dtype).eps, maxval=1.)
  return lax.log(lax.div(x, lax.sub(lax._const(x, 1), x)))


def pareto(key: prng.PRNGKey,
           b: RealArray,
           shape: Optional[Sequence[int]] = None,
           dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Pareto random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    b: a float or array of floats broadcast-compatible with ``shape``
      representing the parameter of the distribution.
    shape: optional, a tuple of nonnegative integers specifying the result
      shape. Must be broadcast-compatible with ``b``. The default (None)
      produces a result shape equal to ``b.shape``.
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified dtype and with shape given by ``shape`` if
    ``shape`` is not None, or else by ``b.shape``.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `pareto` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  if shape is not None:
    shape = core.canonicalize_shape(shape)
  return _pareto(key, b, shape, dtype)

@partial(jit, static_argnums=(2, 3))
def _pareto(key, b, shape, dtype):
  if shape is None:
    shape = np.shape(b)
  else:
    _check_shape("pareto", shape)

  b = lax.convert_element_type(b, dtype)
  e = exponential(key, shape, dtype)
  return lax.exp(e / b)


def t(key: prng.PRNGKey,
      df: RealArray,
      shape: Sequence[int] = (),
      dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample Student's t random values with given shape and float dtype.

  Args:
    key: a PRNGKey used as the random key.
    df: a float or array of floats broadcast-compatible with ``shape``
      representing the parameter of the distribution.
    shape: optional, a tuple of nonnegative integers specifying the result
      shape. Must be broadcast-compatible with ``df``. The default (None)
      produces a result shape equal to ``df.shape``.
    dtype: optional, a float dtype for the returned values (default float64 if
      jax_enable_x64 is true, otherwise float32).

  Returns:
    A random array with the specified dtype and with shape given by ``shape`` if
    ``shape`` is not None, or else by ``df.shape``.
  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `t` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _t(key, df, shape, dtype)

@partial(jit, static_argnums=(2, 3))
def _t(key, df, shape, dtype):
  if shape is None:
    shape = np.shape(df)
  else:
    _check_shape("t", shape, np.shape(df))

  df = lax.convert_element_type(df, dtype)
  key_n, key_g = split(key)
  n = normal(key_n, shape, dtype)
  two = _constant_like(n, 2)
  half_df = lax.div(df, two)
  g = gamma(key_n, half_df, shape, dtype)
  return n * jnp.sqrt(half_df / g)


def rademacher(key: prng.PRNGKey,
               shape: Sequence[int],
               dtype: DTypeLikeInt = dtypes.int_) -> jnp.ndarray:
  """Sample from a Rademacher distribution.

  Args:
    key: a PRNGKey key.
    shape: The shape of the returned samples.
    dtype: The type used for samples.

  Returns:
    A jnp.array of samples, of shape `shape`. Each element in the output has
    a 50% change of being 1 or -1.

  """
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _rademacher(key, shape, dtype)


@partial(jit, static_argnums=(1, 2))
def _rademacher(key, shape, dtype):
  bernoulli_samples = bernoulli(key=key, p=0.5, shape=shape)
  return (2 * bernoulli_samples - 1).astype(dtype)


def maxwell(key: prng.PRNGKey,
            shape: Sequence[int] = (),
            dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample from a one sided Maxwell distribution.

  The scipy counterpart is `scipy.stats.maxwell`.

  Args:
    key: a PRNGKey key.
    shape: The shape of the returned samples.
    dtype: The type used for samples.

  Returns:
    A jnp.array of samples, of shape `shape`.

  """
  # Generate samples using:
  # sqrt(X^2 + Y^2 + Z^2), X,Y,Z ~N(0,1)
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `maxwell` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _maxwell(key, shape, dtype)


@partial(jit, static_argnums=(1, 2))
def _maxwell(key, shape, dtype):
  shape = shape + (3,)
  norm_rvs = normal(key=key, shape=shape, dtype=dtype)
  return jnp.linalg.norm(norm_rvs, axis=-1)


def double_sided_maxwell(key: prng.PRNGKey,
                         loc: RealArray,
                         scale: RealArray,
                         shape: Sequence[int] = (),
                         dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample from a double sided Maxwell distribution.

  Samples using:
     loc + scale* sgn(U-0.5)* one_sided_maxwell U~Unif;

  Args:
    key: a PRNGKey key.
    loc: The location parameter of the distribution.
    scale: The scale parameter of the distribution.
    shape: The shape added to the parameters loc and scale broadcastable shape.
    dtype: The type used for samples.

  Returns:
    A jnp.array of samples.

  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `double_sided_maxwell` must be a float"
                     f" dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _double_sided_maxwell(key, loc, scale, shape, dtype)


@partial(jit, static_argnums=(3, 4))
def _double_sided_maxwell(key, loc, scale, shape, dtype):
  params_shapes = lax.broadcast_shapes(np.shape(loc), np.shape(scale))
  if not shape:
    shape = params_shapes

  shape = shape + params_shapes
  maxwell_key, rademacher_key = split(key)
  maxwell_rvs = maxwell(maxwell_key, shape=shape, dtype=dtype)
  # Generate random signs for the symmetric variates.
  random_sign = rademacher(rademacher_key, shape=shape, dtype=dtype)
  assert random_sign.shape == maxwell_rvs.shape

  return random_sign * maxwell_rvs * scale + loc


def weibull_min(key: prng.PRNGKey,
                scale: RealArray,
                concentration: RealArray,
                shape: Sequence[int] = (),
                dtype: DTypeLikeFloat = dtypes.float_) -> jnp.ndarray:
  """Sample from a Weibull distribution.

  The scipy counterpart is `scipy.stats.weibull_min`.

  Args:
    key: a PRNGKey key.
    scale: The scale parameter of the distribution.
    concentration: The concentration parameter of the distribution.
    shape: The shape added to the parameters loc and scale broadcastable shape.
    dtype: The type used for samples.

  Returns:
    A jnp.array of samples.

  """
  if not dtypes.issubdtype(dtype, np.floating):
    raise ValueError(f"dtype argument to `weibull_min` must be a float "
                     f"dtype, got {dtype}")
  dtype = dtypes.canonicalize_dtype(dtype)
  shape = core.canonicalize_shape(shape)
  return _weibull_min(key, scale, concentration, shape, dtype)


@partial(jit, static_argnums=(3, 4))
def _weibull_min(key, scale, concentration, shape, dtype):
  random_uniform = uniform(
      key=key, shape=shape, minval=0, maxval=1, dtype=dtype)

  # Inverse weibull CDF.
  return jnp.power(-jnp.log1p(-random_uniform), 1.0/concentration) * scale
