package benchmark.provider

object ProviderContract {
    private const val provider = "server-configured-provider"
    private const val model = "server-configured-model"
    fun invoke(snapshot: List<Pair<String, String>>) = snapshot.size
}
