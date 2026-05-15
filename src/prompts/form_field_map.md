# ATS field mapping notes (for the browser-use agent)

These are hints for how to map applicant data onto common ATS field labels. The agent should treat label matching as fuzzy — "Phone number", "Mobile", and "Contact phone" all map to the same value.

## Common fields

| Label patterns | Source field |
|---|---|
| First name | `personal.full_name` (first token) |
| Last name | `personal.full_name` (last token) |
| Preferred name / Nickname / What should we call you | `personal.preferred_name` |
| Email / Email address | `personal.email` |
| Phone / Mobile / Contact number | `personal.phone` |
| City | `personal.location.city` |
| State / Province | `personal.location.province` |
| Country | `personal.location.country` |
| LinkedIn | `personal.links.linkedin` |
| GitHub / Portfolio URL | `personal.links.github`, `personal.links.portfolio` |
| Resume / CV (file upload) | `resume_pdf` |
| Cover letter (file upload) | `cover_pdf` |

## Work authorization

| Label patterns | Source field |
|---|---|
| Are you legally authorized to work in <Canada>? | `screening_answers.authorized_to_work_canada` |
| Will you require sponsorship? | `screening_answers.requires_sponsorship_canada` (Canada) / `work_authorization.us` (US) |
| Are you willing to relocate? | `work_authorization.willing_to_relocate` |
| Remote work preference | `work_authorization.remote_preference` |

## Screening

| Label patterns | Source field |
|---|---|
| How did you hear about us / Source | `screening_answers.how_did_you_hear` |
| Years of experience | `screening_answers.years_of_experience` |
| Desired salary | `preferences.desired_salary_cad` (if "open", use "Negotiable" or skip) |
| Notice period | `preferences.notice_period_weeks` (in weeks; convert to days/months if asked) |
| Earliest start date | `preferences.start_date` |
| Willing to complete a take-home / assessment? | `screening_answers.willing_to_complete_assessment` |
| Comfortable with background check? | `screening_answers.comfortable_with_background_check` |

## EEO / Demographics (US/Canada)

These are ALWAYS optional. Use `demographics.*`. If a value is `"prefer_not_to_say"`, select the "I do not wish to disclose" option if available, otherwise leave the field blank.

| Label patterns | Source field |
|---|---|
| Gender | `demographics.gender` |
| Race / Ethnicity | `demographics.ethnicity` |
| Veteran status | `demographics.veteran_status` |
| Disability status | `demographics.disability_status` |

## Rippling-specific notes

- Rippling forms typically use a single-page layout with sections.
- File uploads are drag-and-drop divs; use the hidden `<input type="file">` directly.
- The "Voluntary Self-Identification" section is always optional.
- Custom screening questions appear after the standard fields — read them carefully and map to the data above; if no match, pause and ask.
