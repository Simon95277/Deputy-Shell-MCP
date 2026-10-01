package benchmark.policy

import benchmark.api.Operation
import benchmark.execution.Executor

/** Server-owned allowlist maps finite intent to fixed implementations. */
object CapabilityRegistry {
    private val implementations = mapOf(
        Operation.INSPECT to Executor::inspect,
        Operation.VALIDATE to Executor::validate,
    )
    fun resolve(operation: Operation) = implementations[operation]
}
