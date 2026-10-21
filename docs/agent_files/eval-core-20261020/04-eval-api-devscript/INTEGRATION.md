# Task 4 engine integration

The API's event loop must remain responsive during adapter reads, git capture, and run-store preparation. B2's synchronous `start_run` and `resume` entrypoints require a running loop and previously combined that preparation with task creation, so putting either entrypoint directly in `asyncio.to_thread` was insufficient.

The authorized integration extracts synchronous preparation, preserves the existing synchronous public entrypoints, and adds `start_run_async` and `resume_async` for the API. Their preparation runs in a worker thread; clients and engine tasks are created on the caller's event loop. Cancellation waits for threaded preparation to finish and releases a prepared lock, leaving any created run interrupted and resumable. Adapter/contract preflight also runs in a worker thread.

This integration is committed separately before the RunManager/routes work so the engine's independent correctness fixes can proceed without conflicting file ownership. Regression tests cover event-loop responsiveness during blocked preparation, cancellation cleanup, and unchanged resume behavior.
