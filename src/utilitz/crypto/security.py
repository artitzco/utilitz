from dataclasses import dataclass


@dataclass(frozen=True)
class SecurityProfile:
    kdf_iterations: int
    salt_size: int = 16
    key_length: int = 32
    kdf_hash: str = "sha256"

    def __post_init__(self) -> None:
        if not isinstance(self.kdf_iterations, int) or self.kdf_iterations <= 0:
            raise ValueError("kdf_iterations must be a positive integer.")

        if not isinstance(self.salt_size, int) or self.salt_size <= 0:
            raise ValueError("salt_size must be a positive integer.")

        if not isinstance(self.key_length, int) or self.key_length <= 0:
            raise ValueError("key_length must be a positive integer.")

        if not isinstance(self.kdf_hash, str) or not self.kdf_hash.strip():
            raise ValueError("kdf_hash must be a non-empty string.")


SECURITY_STANDARD = SecurityProfile(kdf_iterations=100_000)
SECURITY_HIGH = SecurityProfile(kdf_iterations=300_000)
SECURITY_PARANOID = SecurityProfile(kdf_iterations=600_000)
