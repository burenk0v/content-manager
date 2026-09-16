"""Named provider registry used by application composition."""

from collections.abc import Mapping

from .contracts import GenerationProvider, PublicationProvider


class ProviderRegistry:
    def __init__(
        self,
        *,
        generation: Mapping[str, GenerationProvider] | None = None,
        publication: Mapping[str, PublicationProvider] | None = None,
    ) -> None:
        self.generation = dict(generation or {})
        self.publication = dict(publication or {})

    def generation_provider(self, name: str) -> GenerationProvider:
        try:
            return self.generation[name]
        except KeyError as exc:
            raise KeyError(f"unknown generation provider: {name}") from exc

    def publication_provider(self, name: str) -> PublicationProvider:
        try:
            return self.publication[name]
        except KeyError as exc:
            raise KeyError(f"unknown publication provider: {name}") from exc
