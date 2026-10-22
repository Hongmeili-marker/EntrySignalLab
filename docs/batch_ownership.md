# Batch directory ownership and recovery

Version 0.11.0 addresses overlapping checkpoint writers and nested experiment trees. `run_batch` obtains a nonblocking exclusive lease before opening or mutating its output. CLI sweep and uncertainty hold the same lease through execution, plots and final manifest publication. A competing cooperating caller receives a controlled error without changing checkpoint, progress or final output bytes. A process-local registry also rejects same-process overlaps, including ancestors and descendants.

The canonical resolved directory determines a persistent sibling file named `.<directory-name>.entrysignal.lock`. Its existence does not mean a run is active. Do not delete or replace this file: that can create a second inode and split ownership. The lock uses POSIX flock or Windows byte-range locking. It is released on context exit, exceptions or process termination. A fork hook closes inherited descriptors in worker children without explicitly unlocking the parent's lease. A lock prevents overlapping cooperating writers on supported local filesystems; it is not a distributed lease or an assurance about network-filesystem semantics, hostile writers, hard-link aliases or synchronized cloud folders.

## Public Python use

The ordinary `run_batch` API manages ownership. Callers publishing additional artifacts after it returns must hold an outer lease through their final write:

```python
from entrysignallab.locking import DirectoryLock
from entrysignallab.batch import run_batch

with DirectoryLock(output_directory) as lease:
    summary = run_batch(output_directory, params, bounds, rival_delay,
                        metadata, task_factory, config, lock=lease)
    # Publish any additional plots and final manifest here, before release.
```

`metadata` includes the operation and requested case count; the callable `task_factory` must supply every missing case in order. On resume it may omit the already committed prefix. Supplied leases must belong to the same directory, process and thread. They cannot be transferred to a worker or reused after exit.

## Completion and resume

A batch cannot become complete unless the checkpoint contains exactly the declared case count. The factory must supply every missing index in order; an empty remaining factory is allowed when a resumed checkpoint already contains the complete prefix. Too few new cases or indices beyond the declared total raise a controlled error and leave an interrupted checkpoint containing only the committed valid prefix. Resuming requires an explicit flag, no final manifest, matching case hashes and an identical recipe. Runtime identity includes Python patch version and implementation, NumPy and SciPy versions, platform, machine architecture and sampler algorithm. A runtime mismatch is rejected before progress is rewritten. This is a conservative compatibility guard, not a fingerprint of every BLAS binary, CPU instruction or external library.

A killed writer loses its OS lock; an empty persistent lock file is harmless. Resume preserves the last committed prefix, not uncommitted work. Final CSV and summaries are regenerated before completion. Removing a final manifest to force resume is unsupported. Ordinary errors can leave incomplete artifacts without a final manifest. Integrity checks establish correspondence and do not authenticate execution.

## Executed evidence and platform scope

The repair suite and independent validator exercise real competing processes, unchanged bytes on refusal, CLI ownership during real plotting and manifest calls, interrupted recovery, exception release, killed-owner release and inherited descriptor handling on Linux. Windows and macOS code paths are included in installed-wheel CI configuration but were not executed remotely in this release.

Backend references: [Python 3.12 fcntl](https://docs.python.org/3.12/library/fcntl.html), [msvcrt](https://docs.python.org/3.12/library/msvcrt.html), and [os.register_at_fork](https://docs.python.org/3.12/library/os.html#os.register_at_fork). Application behavior is established by the supplied tests, rather than inferred from these API descriptions.

## Directory hierarchy protocol (v0.11.0)

Experiment outputs cannot be nested. A completed or interrupted ancestor with checkpoint.sqlite or an EntrySignalLab manifest blocks child acquisition. An existing descendant experiment blocks parent acquisition. A manifest damaged beyond parsing is treated conservatively as experiment state. Nonexperiment ancestors may contain several sibling outputs.

Before any output-tree write, cooperating same-user processes briefly acquire a coordinator in the shared local temporary directory, in entrysignallab-leases-v2-USERHASH. A catalog maps canonical resolved paths to persistent OS lock files. An active per-path registry lock is held for the whole output lifetime, alongside the legacy sibling lock. The coordinator probes stale entries using nonblocking OS locking, checks ancestor/descendant conflicts and existing experiment state, then atomically commits registration. It is released before computation. This closes the check/create race in both starting orders without serializing sibling workloads. Parent and child refusals precede creation of a sibling lock inside the protected parent tree.

Do not delete or replace coordinator, registry or sibling lock files while processes may use them. Their existence is not activity. A killed process releases OS leases; a later coordinator transaction prunes its stale catalog entry. Fork children close all inherited lease and coordinator descriptors without unlocking the parent. The protocol requires the same OS user, temporary-directory namespace and lock-supporting local filesystem. Different users/namespaces, mixed pre-v0.10 hierarchy protocols, uncooperative writes and distributed/network storage are outside its guarantee. Symlink paths are resolved; hard-link aliases are not a directory identity mechanism.

Prepared sweep metadata now contains task_generator_version and normalized axes, retaining each list's order and duplicates. The resume recipe binds these values independently of caller config. Use the returned factory with its matching metadata; arbitrary custom factories remain responsible for their declared task content. Exact prefix/cardinality rules remain in effect.


## v0.12.0 task sequence validation

Recovery filters only a fixed committed prefix. A supplied full factory starts at 0 and is contiguous; an omitted-prefix factory starts exactly at resume_prefix. Both reject duplicate/backward indices, including malformed supplied prefix entries. A completed prefix may use an empty factory. Serial/process paths share this validation; process prefetch can discover an error before the same number of cases has committed as in serial execution. Existing committed results are retained. Directory lease guarantees and the local filesystem/user/temp scope do not change.
