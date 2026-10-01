package benchmark.privacy

object SourceSelector {
    // Deployment policy is server-owned; callers cannot submit paths or policy.
    private val allowed = listOf("app/src/", "tools/")
    fun select(tracked: List<String>) = tracked.filter { path -> allowed.any(path::startsWith) }
}
