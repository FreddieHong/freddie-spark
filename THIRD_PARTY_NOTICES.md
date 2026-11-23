# Third-party components

Freddie Lingua uses these components; upstream license terms continue to apply.

- Python: Python Software Foundation License, https://www.python.org/psf/license/
- python-build-standalone: upstream bundled notices, https://github.com/astral-sh/python-build-standalone
- MLX, MLX Whisper and MLX LM: MIT license, https://github.com/ml-explore
- Whisper model: OpenAI MIT license, https://github.com/openai/whisper
- Qwen2.5-1.5B-Instruct: Apache-2.0, https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct
- Hugging Face Hub: Apache-2.0, https://github.com/huggingface/huggingface_hub
- FFmpeg: this local build includes GPL components. License and build information: run the bundled `ffmpeg -L` and `ffmpeg -buildconf`; source: https://ffmpeg.org/ and https://formulae.brew.sh/formula/ffmpeg
- Additional Python and FFmpeg dependencies retain their individual licenses in their distributions. Review them before redistribution.

ModelScope provides hosted copies of the selected model repositories. Downloads are verified against file hashes and expected weight hashes. The model code is not downloaded or executed; the application uses the installed MLX implementation.
