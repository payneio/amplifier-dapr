"""Tests for svc-machine Dockerfile configuration."""

import pathlib


DOCKERFILE_PATH = pathlib.Path(__file__).parent.parent.parent.parent / "services" / "svc-machine" / "Dockerfile"


def _dockerfile_contents() -> str:
    return DOCKERFILE_PATH.read_text()


def test_dockerfile_installs_ripgrep():
    """Stage 2 of the Dockerfile must install ripgrep via apt-get."""
    contents = _dockerfile_contents()
    expected_line = "RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*"
    assert expected_line in contents, (
        f"Expected Dockerfile to contain ripgrep installation line:\n"
        f"  {expected_line}\n"
        f"Actual Dockerfile content:\n{contents}"
    )


def test_dockerfile_ripgrep_in_stage2():
    """The ripgrep install line must appear in Stage 2 (after FROM amplifier-service-base)."""
    contents = _dockerfile_contents()
    stage2_marker = "FROM amplifier-service-base"
    ripgrep_line = "RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*"

    stage2_start = contents.find(stage2_marker)
    assert stage2_start != -1, "Stage 2 'FROM amplifier-service-base' not found in Dockerfile"

    stage2_content = contents[stage2_start:]
    assert ripgrep_line in stage2_content, (
        "ripgrep installation line must be in Stage 2 (after FROM amplifier-service-base)"
    )


def test_dockerfile_ripgrep_before_copy():
    """The ripgrep install line must appear before the COPY lines in Stage 2."""
    contents = _dockerfile_contents()
    stage2_marker = "FROM amplifier-service-base"
    ripgrep_line = "RUN apt-get update && apt-get install -y ripgrep && rm -rf /var/lib/apt/lists/*"
    copy_sdk_line = "COPY amplifier-service-sdk/ /amplifier-service-sdk/"

    stage2_start = contents.find(stage2_marker)
    assert stage2_start != -1, "Stage 2 'FROM amplifier-service-base' not found"

    stage2_content = contents[stage2_start:]
    ripgrep_pos = stage2_content.find(ripgrep_line)
    copy_pos = stage2_content.find(copy_sdk_line)

    assert ripgrep_pos != -1, "ripgrep installation line not found in Stage 2"
    assert copy_pos != -1, "COPY amplifier-service-sdk line not found in Stage 2"
    assert ripgrep_pos < copy_pos, (
        "ripgrep installation line must appear before COPY lines in Stage 2"
    )
