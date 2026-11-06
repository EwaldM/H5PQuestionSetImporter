# H5P Question Set Text Importer

[![Licence: MIT](https://img.shields.io/badge/Licence-MIT-blue.svg)](LICENSE)
[![Python tests](https://img.shields.io/badge/tests-unittest-blue.svg)](#testing)

A standalone Python 3.10+ script for **creating or updating an H5P Question Set from a UTF-8 text file**. It uses an existing `.h5p` package as the complete source of H5P libraries and settings; it does not require Moodle, an H5P server, or third-party Python packages.

Supported package versions (verified with the supplied examples):

- `H5P.QuestionSet` **1.20**
- `H5P.MultiChoice` **1.16**, exclusively (questions of other H5P content types are rejected)

The script will reject unsupported package versions rather than assuming that their JSON schemas are compatible.

## Repository layout

```text
h5p_question_set.py          Python CLI (no third-party dependencies)
Import-H5P.cmd              Windows drag-and-drop launcher
examples/sample_questions.txt  Example quiz input
README.md                   Documentation and usage
LICENSE                     MIT licence
ATTRIBUTION.md              Copyright and third-party acknowledgements
CONTRIBUTING.md             Contribution guidelines
tests/                      Self-contained unittest suite
.github/workflows/tests.yml GitHub Actions test workflow
```

**Not included:** `template.h5p`. Supply an H5P Question Set you are authorised to use. H5P packages are ignored by Git to avoid accidentally committing third-party libraries or training content.


## Input format

One question per blank-line-separated block:

```text
Question text
*Correct answer:Hint:Feedback if chosen:Feedback if not chosen
Incorrect answer:Hint:Feedback if chosen:Feedback if not chosen
*Another correct answer:Hint:Feedback if chosen:Feedback if not chosen

Next question
*Correct answer:Hint:Feedback if chosen:Feedback if not chosen
Another answer:Hint:Feedback if chosen:Feedback if not chosen
```

Rules:

- The **first line** of each block contains the question.
- Each subsequent line contains exactly **four fields separated by three colons**: answer, hint, chosen feedback, not-chosen feedback.
- A leading `*` marks a correct answer. Each question must have at least one correct answer.
- The number of questions and answer alternatives is unrestricted, subject to H5P's normal constraints. A question must have at least one answer.
- Hints and feedback fields may be empty, but their colons must still be present. For example, `*Yes:::`.
- UTF-8 (with or without a byte-order mark) and Windows/Unix line endings are accepted.
- All text is treated as **literal text**, not HTML: `&`, `<` and `>` are safely encoded for H5P's HTML-based fields.
- **Colons within an answer field, hint or feedback are not supported**, since the samples define no escaping convention. The script reports an error with the line number instead of guessing how to split such lines. A colon in the question line is fine.
- Leading/trailing whitespace on nonblank lines or on individual fields is rejected instead of silently being trimmed.
- The entire input is validated before writing the output.

## Command-line interface

On Windows, run the script with `py -3` (or `python`). Paths containing spaces should be quoted.
**`create` is the default mode**, so the mode name may be omitted. The question text file can be supplied either as a **positional argument** or by `--text` (not both).

### Create a new H5P package (default mode)

Place an H5P Question Set package named **`template.h5p` in the same folder as `h5p_question_set.py`**. The default template path is resolved from the *script's directory*, independent of the current working directory and the Windows shortcut's **Start in** field. An explicit `--template` path overrides this default. The default template is **not** bundled with this script: copy one of your existing, suitable H5P Question Set packages and rename that copy to `template.h5p`.

Shortest invocation:

```powershell
py -3 h5p_question_set.py "C:\Quizzes\My Questions.txt"
```

Equivalent invocations:

```powershell
py -3 h5p_question_set.py create "C:\Quizzes\My Questions.txt"
py -3 h5p_question_set.py --text "C:\Quizzes\My Questions.txt"
```

Specify a different template using `--template`:

```powershell
py -3 h5p_question_set.py "C:\Quizzes\My Questions.txt" `
  --template "C:\Templates\Question Set Template.h5p"
```

All of these commands create `C:\Quizzes\My Questions.h5p` with H5P title `My Questions`, unless `--output` or `--title` overrides the corresponding default. The original template is retained intact, except when you explicitly select the same output path and use `--overwrite`.

The first existing question in the template is used as the blueprint for the new MultiChoice questions' non-text settings. All generated questions receive **new `subContentId` UUIDs**. The existing questions must have identical non-text parameters and metadata to avoid an ambiguous blueprint. If they differ, the script reports an error.

**Name collision:** If the text file's derived output `.h5p` already exists, the script refuses to replace it unless `--overwrite` is supplied. This applies whether the existing output is another quiz or the template itself.

### Windows 11: drag a text file onto a shortcut

The package contains `Import-H5P.cmd`, a launcher specifically for dragging and dropping a text file onto a Windows shortcut.

1. Put `h5p_question_set.py` and `Import-H5P.cmd` together in a folder, for example `C:\Tools\H5P`. Add your `template.h5p` to **that same folder**.
2. Right-click `Import-H5P.cmd` and choose **Create shortcut** (on Windows 11, use **Show more options** first if necessary). Move the shortcut to your desktop.
3. Drag `C:\Quizzes\My Questions.txt` onto the shortcut.
4. The script creates `C:\Quizzes\My Questions.h5p`, with title `My Questions`. The console stays open until you press a key, showing the outcome or any validation error.

The launcher contains:

```bat
@echo off
setlocal
if "%~1"=="" (
    echo Drag a question .txt file onto a shortcut to this launcher.
    echo.
    pause
    exit /b 2
)
py -3 "%~dp0h5p_question_set.py" "%~1"
set "result=%errorlevel%"
echo.
pause
exit /b %result%
```

`%~dp0` is the launcher's own folder, and `%~1` is the dropped file's full path without surrounding quotation marks; quoting both paths ensures spaces are handled correctly. Only the first dropped file is processed by the supplied launcher. Python 3.10 or later and the Windows `py` launcher must be installed.

**Without the CMD launcher:** A Windows shortcut can also launch `py.exe` with the Python script as a fixed argument. For example, use the following fields in the shortcut properties, adjusting the actual paths:

```text
Target:   C:\Windows\py.exe -3 "C:\Tools\H5P\h5p_question_set.py"
Start in: C:\Tools\H5P
```

Dropping `C:\Quizzes\My Questions.txt` onto that shortcut appends the dropped file path to the command, effectively running:

```powershell
C:\Windows\py.exe -3 "C:\Tools\H5P\h5p_question_set.py" "C:\Quizzes\My Questions.txt"
```

The CMD launcher is preferable because it keeps error messages visible. `C:\Windows\py.exe` is a common location for the Python launcher, but its location can differ. Use the path returned by `where py` if needed.

### Update an existing H5P package

Update mode remains **explicit** and requires `--source`:

```powershell
py -3 h5p_question_set.py update "C:\Quizzes\My Questions.txt" `
  --source "C:\Quizzes\Existing Quiz.h5p"
```

The previous `--text` form remains available:

```powershell
py -3 h5p_question_set.py update `
  --text "C:\Quizzes\My Questions.txt" `
  --source "C:\Quizzes\Existing Quiz.h5p"
```

The **full question list is replaced**, not appended to. Existing Question Set properties are left unchanged except for the H5P title. For each existing question position, the new text/answers replace the old text/answers, while its other MultiChoice properties and metadata are preserved. **Every output question receives a fresh `subContentId` UUID**, including position-matched questions in update mode. If the input contains additional questions, they use the first original question as a blueprint, provided the existing questions have uniform non-text settings/metadata; otherwise an error is reported rather than guessing. Excess original questions are omitted.

The default output path is the text file's path with `.h5p` extension; the default H5P title is its filename without extension. If the output already exists, use `--overwrite` or choose another file with `--output`.

### Update in place

To update a specific H5P package in place, set source and output to the same path and explicitly permit replacement:

```powershell
py -3 h5p_question_set.py update "C:\Quizzes\My Questions.txt" `
  --source "C:\Quizzes\Existing Quiz.h5p" `
  --output "C:\Quizzes\Existing Quiz.h5p" `
  --overwrite
```

Output is written to a temporary file and checked before the original is atomically replaced. There is **no automatic backup**. Without `--overwrite`, an existing output is never replaced.

## Optional behavioural overrides

The following parameters override the named properties **on every output MultiChoice question**:

| H5P editor label | Command-line parameter | JSON property |
| --- | --- | --- |
| Give one point for the whole task | `--single-point true\|false` | `params.behaviour.singlePoint` |
| Randomize answers | `--random-answers true\|false` | `params.behaviour.randomAnswers` |
| Require answer before the solution can be viewed | `--require-answer true\|false` | `params.behaviour.showSolutionsRequiresInput` |

Each argument is optional. **When omitted, the value from that question or its template is preserved**. For example:

```powershell
py -3 h5p_question_set.py update `
  --text "Quiz for Video - Trigger.txt" `
  --source "Existing Quiz.h5p" `
  --output "Updated Quiz.h5p" `
  --single-point false `
  --random-answers true `
  --require-answer true
```

The script inherits these values from the selected template or source package. The other Question Set and MultiChoice settings are also inherited, not silently reset to library defaults.

### Other options

- `--output "Other Filename.h5p"`: Overrides the default output path (the text file's path with `.h5p` extension).
- `--title "Quiz title"`: Overrides the default title (text filename without extension) in `h5p.json` `title` and, if present, `extraTitle`.
- By default, the script **removes `content/config.json`** from generated packages in both create and update modes. This nonstandard file may contain an obsolete absolute Windows path from the source package.
- `--keep-local-config`: Explicitly preserves `content/config.json` as-is, for workflows that require this application-specific metadata.
- `--remove-local-config`: Legacy option retained for compatibility. Removal is already the default. It cannot be combined with `--keep-local-config`.
- `--overwrite`: Permits replacing the output file, including the same path as the input H5P file.
- `-h` / `--help`: Shows available commands and options, including subcommand help (`create --help` and `update --help`).

## Handling of existing H5P package inconsistencies

The script does **not** silently normalise the following source-package conditions:

1. Some MultiChoice packages may set `params.behaviour.singleAnswer=true`, including questions with multiple correct answers. `behaviour.type=auto` makes the H5P MultiChoice runtime calculate this flag from the actual number of correct answers. The stored field is preserved rather than rewritten.
2. A package may omit `texts.questionSetInstruction` (which normally defaults to `Choose question to display`). That field is left as-is.
3. `content/config.json` may contain obsolete absolute paths. It is omitted by default for portability and privacy; use `--keep-local-config` if an editor requires retaining it.
4. Question metadata titles may be generic, e.g. `Untitled Multiple Choice`. They are preserved, not derived from the question text.

## Validation and errors

The script returns exit code **0** on success and **2** for validation/package errors. It checks that:

- The input is readable UTF-8 text and the H5P file is an intact ZIP archive.
- Each question has the expected answer format and at least one correct answer.
- The H5P source uses the supported Question Set and MultiChoice versions.
- Every existing question is MultiChoice and has the expected parameter structures.
- Embedded question media are absent (the text format does not describe media).
- The blueprint is unambiguous when new question objects must be generated.
- The output is an intact ZIP containing the intended `content/content.json`.

A malformed answer containing extra colons, for example, produces a line-numbered validation error. No output file is created on validation failure.

## Testing

Run the self-contained test suite with no additional packages:

```powershell
py -3 -m unittest discover -s tests -p "test_*.py" -v
```

GitHub Actions runs the same tests on Python 3.10, 3.12 and 3.13. Tests build synthetic H5P ZIP fixtures in temporary directories; they do **not** require private course examples or a downloadable H5P library. These fixtures verify the importer's file and JSON transformations, **not** that a synthetic package is playable in Moodle. Use your own real Question Set template for Moodle integration testing.

## Publishing and updating on GitHub

The repository is available at [EwaldM/H5PQuestionSetImporter](https://github.com/EwaldM/H5PQuestionSetImporter).

To update the **existing** repository with these licensing changes, copy the
new `LICENSE`, `README.md` and `ATTRIBUTION.md` files into your local
repository folder, replacing those files. Then execute the following from
Git Bash in the repository directory:

```bash
git add LICENSE README.md ATTRIBUTION.md
git commit -m "Change project licence to MIT"
git push origin main
```

This only changes the licence and documentation; the Python script, launcher,
examples and tests are unchanged. No new `git init` or `git remote add` is
needed.

## Shortcut icon

A multi-resolution Windows shortcut icon is supplied as
[`assets/H5P-Question-Set-Shortcut.ico`](assets/H5P-Question-Set-Shortcut.ico).
To use it, open your shortcut's **Properties → Shortcut → Change Icon** and
select this ICO file.

The artwork is based on the H5P Question Set icon, copyright Joubel AS,
licensed under MIT. See [ATTRIBUTION.md](ATTRIBUTION.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and the
upstream licence notice.

## Licence

This project is licensed under the **[MIT licence](LICENSE)**.
Copyright (c) 2026 EwaldM. The MIT licence permits use, modification,
redistribution and commercial use, provided that its copyright and permission
notices are retained in copies or substantial portions.

See [ATTRIBUTION.md](ATTRIBUTION.md) for copyright acknowledgements, the scope
of the project licence, and the fact that earlier CC BY 4.0 releases retain
their original licensing terms. The MIT licence does not apply to third-party
H5P libraries or to externally supplied quiz content.

## References

- [H5P Question Set semantics](https://github.com/h5p/h5p-question-set/blob/master/semantics.json)
- [H5P MultiChoice semantics](https://github.com/h5p/h5p-multi-choice/blob/master/semantics.json)
- [H5P Question Set repository](https://github.com/h5p/h5p-question-set)
- [H5P MultiChoice repository](https://github.com/h5p/h5p-multi-choice)
