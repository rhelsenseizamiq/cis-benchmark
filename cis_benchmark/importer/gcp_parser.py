from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Google Cloud Platform Foundation Benchmark",
    appendix_marker="Appendix: Recommendation Summary",
    classification_words=["Manual", "Automated"],
    known_versions=["1.2.0"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
