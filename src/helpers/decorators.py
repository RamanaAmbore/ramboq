import inspect
import threading
import time
from functools import wraps
from inspect import iscoroutinefunction

from src.helpers.ramboq_logger import get_logger

logger = get_logger(__name__)


def singleton_init_guard(init_func):
    @wraps(init_func)
    def wrapper(self, *args, **kwargs):
        if getattr(self, '_singleton_initialized', False):
            logger.debug(f"Instance for {self.__class__.__name__} already initialized.")
            return
        init_func(self, *args, **kwargs)
        self._singleton_initialized = True

    return wrapper


def retry_kite_conn(max_attempts: int):
    """
    Decorator to retry a function on failure.

    If the decorated function declares a `test_conn` parameter in its
    signature, the decorator will set `test_conn=True` starting from the
    second attempt.
    """

    def decorator(func):
        sig = inspect.signature(func)
        has_test_conn = "test_conn" in sig.parameters  # ✅ explicit check

        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    # Only from 2nd attempt onwards, add/overwrite test_conn
                    if attempt >= 1 and has_test_conn:
                        kwargs["test_conn"] = True

                    return func(*args, **kwargs)

                except Exception as e:
                    logger.warning(
                        f"{func.__name__}: Attempt {attempt + 1} of {max_attempts} failed: {e}..."
                    )
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"{func.__name__}: Operation failed after {max_attempts} attempts."
                        )
                        raise

        return wrapper

    return decorator


def track_it():
    def decorator(func):
        if iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    raise e
                finally:
                    elapsed = time.perf_counter() - start_time
                    logger.info(f"Async function {func.__name__} executed in {elapsed:.4f} seconds")

            return async_wrapper

        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    raise e
                finally:
                    elapsed = time.perf_counter() - start_time
                    logger.info(f"Function {func.__name__} executed in {elapsed:.4f} seconds")

            return sync_wrapper

    return decorator


def lock_it_for_update(method):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)

    return wrapper


def update_lock(method):
    """
    Decorator that ensures method execution is thread-safe using global and per-element locks.
    The element key is assumed to be the first positional argument.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        key = args[0] if args else None  # get key if passed

        with self.lock:
            if key:
                if key not in self.element_locks:
                    self.element_locks[key] = threading.Lock()
                lock = self.element_locks[key]
            else:
                lock = self.lock

        with lock:
            return method(self, *args, **kwargs)

    return wrapper


def for_all_accounts(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        result_dict = {}

        # Call once with defaults → this gives us connections object
        bound_func = func.__wrapped__ if hasattr(func, "__wrapped__") else func

        # Use inspect to get defaults but don’t override
        import inspect
        sig = inspect.signature(bound_func)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()

        connections = bound.arguments["connections"]()
        account = bound.arguments.get("account", None)
        conn = bound.arguments.get("conn", None)
        results = []

        # Case 1: Single account
        if account:
            if not conn:
                kwargs["kite"] = connections.conn[account].get_kite_conn(test_conn=True)
                result = func(*args, **kwargs)
                results.append(result)
            return results

        # Case 2: All accounts -> run func for each account
        for acc in connections.conn.keys():
            new_kwargs = kwargs.copy()
            new_kwargs["account"] = acc
            new_kwargs["kite"] = connections.conn[acc].get_kite_conn(test_conn=True)
            result = func(*args, **new_kwargs)  # ✅ fix: use new_kwargs
            results.append(result)
        return results

    return wrapper
