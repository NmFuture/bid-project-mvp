# Paragraph Judge

This directory will hold paragraph judge prompts and calibration data.

Rules inherited from the evaluation boundary in [`../README.md`](../README.md):

- Use a model and prompt chain independent from the filling skills.
- Use the judge only for `paragraph` fields.
- Calibrate against 100 manually double-labeled fields before relying on
  automated paragraph scores.
