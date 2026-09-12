import uvicorn

from ppe_api.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run("ppe_api.main:app", host=settings.host, port=settings.port, factory=False)


if __name__ == "__main__":
    main()
