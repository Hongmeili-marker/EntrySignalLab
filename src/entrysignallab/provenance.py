"""Automatically observed runtime and hardware context. MIT License."""
from pathlib import Path
import os, platform, sys
import numpy, scipy, matplotlib

def environment_record():
    def read(path):
        try: return Path(path).read_text().strip()
        except OSError: return None
    cpu_model = None
    info = read('/proc/cpuinfo')
    if info:
        cpu_model = next((s.split(':',1)[1].strip() for s in info.splitlines() if s.startswith('model name')),None)
    quota = read('/sys/fs/cgroup/cpu.max')
    memory = read('/sys/fs/cgroup/memory.max')
    try: affinity = sorted(os.sched_getaffinity(0))
    except (AttributeError,OSError): affinity = None
    return {'python':sys.version,'numpy':numpy.__version__,'scipy':scipy.__version__,
            'matplotlib':matplotlib.__version__,'platform':platform.platform(),
            'machine':platform.machine(),'cpu_model':cpu_model,'host_logical_cpus':os.cpu_count(),
            'affinity_cpus':affinity,'cgroup_cpu_max':quota,'cgroup_memory_max':memory,
            'venv':sys.prefix,'base_prefix':sys.base_prefix,
            'isolated_venv':sys.prefix!=sys.base_prefix and not any('/site-packages' in p and not p.startswith(sys.prefix) for p in sys.path),
            'hardware_scope':'Automatically read container/host-visible fields; unavailable fields are null. Host counts do not establish allocated performance.'}
