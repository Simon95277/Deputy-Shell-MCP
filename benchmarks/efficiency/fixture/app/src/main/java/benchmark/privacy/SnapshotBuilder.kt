package benchmark.privacy

object SnapshotBuilder {
    fun copyCandidate(paths: List<String>) = paths.map { it to "candidate-bytes:$it" }
    fun publish(candidate: List<Pair<String, String>>) = candidate.toList()
}
