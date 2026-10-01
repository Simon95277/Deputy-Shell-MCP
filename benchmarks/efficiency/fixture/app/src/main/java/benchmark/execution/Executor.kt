package benchmark.execution

import benchmark.api.CallerRequest
import benchmark.policy.CapabilityRegistry

/** Server selects the executable and builds a fixed bounded invocation. */
object Executor {
    private val root = "configured-repository"
    private val program = "trusted-validator"
    data class Invocation(val executable: String, val argv: List<String>)
    fun inspect(request: CallerRequest) = Invocation(program, listOf("--root", root, "--mode", "inspect"))
    fun validate(request: CallerRequest) = Invocation(program, listOf("--root", root, "--mode", "validate"))
    fun dispatch(request: CallerRequest): Any {
        val implementation = CapabilityRegistry.resolve(request.operation)
            ?: error("operation is not registered")
        return implementation(request)
    }
}
