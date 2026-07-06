# Do not add a cross-process build lock

Build commands do not create a filesystem lock such as `.build.lock`. `preprocess` and `build-index` each enforce only their own in-process concurrency limits for model calls, retries, and writes.

Operators should not run multiple build commands that write the same `data/processed/` artifacts at the same time. This keeps the first implementation simpler and matches the project scale, where builds are explicit local CLI operations rather than background server jobs.

