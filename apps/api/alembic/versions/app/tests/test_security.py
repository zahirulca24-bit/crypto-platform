import pytest
from security import hash_password, verify_password, validate_password


def test_hashing_returns_non_plaintext_hash():
    password = "SecurePassword123"
    hashed = hash_password(password)
    assert hashed != password
    assert "$argon2id$" in hashed


def test_valid_password_verifies_successfully():
    password = "SecurePassword123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_incorrect_password_fails_verification():
    password = "SecurePassword123"
    wrong_password = "WrongPassword456"
    hashed = hash_password(password)
    assert verify_password(wrong_password, hashed) is False


def test_hashing_same_password_produces_unique_hashes():
    password = "SecurePassword123"
    hash1 = hash_password(password)
    hash2 = hash_password(password)
    assert hash1 != hash2
    assert verify_password(password, hash1) is True
    assert verify_password(password, hash2) is True


def test_empty_password_rejected():
    with pytest.raises(ValueError, match="Password cannot be empty"):
        hash_password("")


def test_password_shorter_than_8_rejected():
    with pytest.raises(ValueError, match="at least 8 characters"):
        hash_password("short7")


def test_password_longer_than_128_rejected():
    long_password = "a" * 129
    with pytest.raises(ValueError, match="exceed 128 characters"):
        hash_password(long_password)


def test_boundary_lengths_accepted():
    min_pass = "a" * 8
    max_pass = "a" * 128
    hash_min = hash_password(min_pass)
    hash_max = hash_password(max_pass)
    assert verify_password(min_pass, hash_min) is True
    assert verify_password(max_pass, hash_max) is True

