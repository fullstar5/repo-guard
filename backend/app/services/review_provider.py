# define AI provider interface


from abc import ABC, abstractmethod



class ReviewProvider(ABC):
    @abstractmethod
    async def review_chunk(self, chunk_content: str) -> str:
        raise NotImplementedError