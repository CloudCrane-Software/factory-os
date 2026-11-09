import numpy as np
import astropy
from astropy import units as u

print("numpy", np.__version__, "| astropy", astropy.__version__)
print("float16 scalar * u.km ->", (np.float16(1) * u.km).dtype)
print("float32 scalar * u.km ->", (np.float32(1) * u.km).dtype)
print("float64 scalar * u.km ->", (np.float64(1) * u.km).dtype)
print("float128 scalar* u.km ->", (np.longdouble(1) * u.km).dtype)
print("int64 scalar * u.km ->", (np.int64(1) * u.km).dtype)
print("bool scalar * u.km ->", (np.bool_(1) * u.km).dtype)
a16 = np.array([1.0, 2.0], dtype=np.float16)
print("float16 array Quantity ->", u.Quantity(a16, u.yr).dtype)
print("Quantity(q16) rebuild ->", u.Quantity(u.Quantity(a16, u.yr)).dtype)
ast = np.array([(1.0, 2.0)], dtype=[("a", "<f8")])
print("structured ->", u.Quantity(ast, u.m).dtype)
obj = np.array([1.0, 2.0], dtype=object)
print("object array ->", u.Quantity(obj, u.m).dtype)
big = np.array([2**62], dtype=np.int64) * u.Gm
print("int64 big value * u.Gm ->", big.value[0] > 0, "(no overflow)")
