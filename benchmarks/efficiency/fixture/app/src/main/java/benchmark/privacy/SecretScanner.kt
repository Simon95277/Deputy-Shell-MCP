package benchmark.privacy

object SecretScanner {
    fun scan(candidate: List<Pair<String, String>>) = candidate.none { (_, bytes) -> bytes.contains("PRIVATE KEY") }
}
