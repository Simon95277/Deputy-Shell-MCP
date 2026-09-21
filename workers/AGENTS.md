# DeputyWorkers operating contract

Workers are the deterministic, bounded execution subsystem. The server owns
paths, executables, capability mapping, and evidence boundaries. Keep the
fixed capability registry and fail closed on unsupported authority.

Workers remain independent from the advisory Agents subsystem. Do not expose
generic shell, arbitrary processes, arbitrary filesystem paths, generic ADB,
or caller-selected execution authority.
