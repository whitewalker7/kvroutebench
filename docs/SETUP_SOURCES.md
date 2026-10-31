# Setup sources checked before the first hands-on session

Checked on 2026-10-25. These are upstream metadata checks, not evidence that a
local download, container, or inference request has succeeded.

## Model artifact

The official Qwen repository lists `qwen2.5-0.5b-instruct-q4_k_m.gguf`,
approximately 491 MB. Download only this artifact, not the complete repository
of alternative quantizations (approximately 5.37 GB).

- Repository: `Qwen/Qwen2.5-0.5B-Instruct-GGUF`
- Repository revision: `9217f5db79a29953eb74d5343926648285ec7e67`
- Filename: `qwen2.5-0.5b-instruct-q4_k_m.gguf`
- Expected SHA256 from the upstream file page:
  `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db`
- Revision-specific download URL:
  <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/9217f5db79a29953eb74d5343926648285ec7e67/qwen2.5-0.5b-instruct-q4_k_m.gguf>

Verify the downloaded file's SHA256 before treating it as the model for recorded
runs. The hash above is expected metadata, not a local verification result.

Sources: [repository revision](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/commit/9217f5db79a29953eb74d5343926648285ec7e67),
[file metadata and checksum](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/blob/main/qwen2.5-0.5b-instruct-q4_k_m.gguf).

## Worker runtime

The official llama.cpp documentation lists
`ghcr.io/ggml-org/llama.cpp:server` as the CPU server image, including linux/amd64
support. The tag is mutable: resolve and record a digest before experimental use.
Do not claim its compatibility or reproducibility from documentation alone.

The upstream release page currently identifies `v0.7.0` as a source-release
candidate. An identically named container tag has not been verified. Source
release identity and container image identity must not be conflated.

Specify the bind address, port, thread counts, context size, and parallel slots
explicitly. Inspect the chosen binary's version/help and actual startup settings.

Sources: [official Docker documentation](https://github.com/ggml-org/llama.cpp/blob/v0.7.0/docs/docker.md),
[source release](https://github.com/ggml-org/llama.cpp/releases/tag/v0.7.0).

## Recorded local setup

The pinned model checksum and worker build were verified locally. See
`configs/model.json`, `configs/worker-image.json`, and the completed comparison
in `demo/evidence/`. The current reproduction steps are in the root README.
