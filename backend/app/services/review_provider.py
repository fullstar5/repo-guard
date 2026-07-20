# define AI provider interface


from abc import ABC, abstractmethod



class ReviewProvider(ABC):
    @abstractmethod
    async def review_content(self, content: str) -> str:
        """Review one prepared input payload and return model output."""
        raise NotImplementedError