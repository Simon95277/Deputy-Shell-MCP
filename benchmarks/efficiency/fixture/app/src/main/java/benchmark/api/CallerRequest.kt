package benchmark.api

/** Public input carries a finite intent, never process material or host paths. */
data class CallerRequest(val operation: Operation, val parameters: Map<String, String>)
enum class Operation { INSPECT, VALIDATE }
