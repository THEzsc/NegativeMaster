"""Keep independent native workers from each occupying every CPU core."""
import os


def configure_threads(environ=None):
    env = os.environ if environ is None else environ
    try:
        threads = min(4, max(1, int(env.get('NM_ENGINE_THREADS', '2'))))
    except (TypeError, ValueError):
        threads = 2
    # Set before importing NumPy/LibRaw. Inherited shell defaults can be much larger.
    for name in ('OMP_NUM_THREADS', 'OMP_THREAD_LIMIT', 'OPENBLAS_NUM_THREADS',
                 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[name] = str(threads)
    env['OMP_WAIT_POLICY'] = 'PASSIVE'
    env['KMP_BLOCKTIME'] = '0'
    return threads
