from setuptools import find_packages, setup


setup(
    name="setu-payment-service",
    version="0.1.0",
    description="Reviewer-first backend service for Setu payment event ingestion.",
    packages=find_packages(include=["app", "app.*"]),
    install_requires=[
        "fastapi>=0.110,<1.0",
        "uvicorn[standard]>=0.27,<1.0",
        "sqlalchemy>=2.0,<3.0",
        "alembic>=1.13,<2.0",
        "asyncpg>=0.29,<1.0",
        "psycopg[binary]>=3.1,<4.0",
        "pydantic>=2.6,<3.0",
    ],
    extras_require={
        "dev": [
            "httpx>=0.27,<1.0",
            "pytest>=8.0,<9.0",
            "pytest-asyncio>=0.23,<1.0",
            "aiosqlite>=0.20,<1.0",
        ]
    },
)
