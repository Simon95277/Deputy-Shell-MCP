package benchmark.privacy

import benchmark.provider.ProviderContract

object Publisher {
    fun run(tracked: List<String>): Any {
        val selected = SourceSelector.select(tracked)
        val candidate = SnapshotBuilder.copyCandidate(selected)
        check(SecretScanner.scan(candidate))
        val sourceAfterValidation = SourceSelector.select(tracked)
        check(sourceAfterValidation == selected)
        val recapturedCandidate = SnapshotBuilder.copyCandidate(sourceAfterValidation)
        check(CoherenceVerifier.sameBytes(candidate, recapturedCandidate))
        val snapshot = SnapshotBuilder.publish(candidate)
        return ProviderContract.invoke(snapshot)
    }
}
