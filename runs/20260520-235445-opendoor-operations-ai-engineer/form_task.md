You are filling out a job application form for Opendoor — Operations AI Engineer.

APPLY URL: https://ats.rippling.com/en-CA/opendoor/jobs/f572e889-0644-4590-8a5a-64f73d7db17d/apply?step=application

YOUR GOAL:
1. Navigate to the apply URL.
2. **Scroll all the way through the form first**, top to bottom, to learn what fields exist BEFORE filling anything. Forms often have collapsed or below-the-fold sections (work authorization, screening questions, custom Qs) that aren't visible on initial load. Build a mental map of every section.
3. Fill every applicable field using the applicant data below — go SECTION BY SECTION, top to bottom. Do not skip fields just because they look optional unless the data explicitly says so (e.g., demographics are optional, screening questions are not).
4. Upload the resume and cover letter PDFs at the indicated paths.
5. STOP at the final submit/review step. DO NOT click submit. Take a full-page
   screenshot of the completed form for human review, then exit.

FIELD REFERENCE — the form MAY contain any subset of the fields below. It is normal and expected that a given ATS only asks for some of these. Fill every field that is PRESENT on the form using the data above. Do NOT treat an absent field as a problem, do NOT hunt for fields that aren't there, and do NOT report missing fields as a failure — many ATS forms are intentionally short.

Possible fields (fill the ones that exist):
  - Personal: first name, last name, preferred name, email, phone, location, LinkedIn, GitHub, portfolio, current company
  - Work authorization: authorized to work, requires sponsorship, US status, willing to relocate, remote preference
  - Screening: years of experience, desired salary, notice period, start date, how did you hear, assessment willingness, background check consent, any custom questions
  - Files: resume PDF, cover letter PDF (verify the filename appears on the form, not "No file chosen")
  - Demographics/EEO (optional): fill from the data, or select "prefer not to say"; never invent

COMPLETION SIGNAL — the form is complete when the Apply/Submit button is ENABLED (not greyed out). A disabled button means a required field on the form is still empty: scroll the whole form and find it. An enabled button means every required field this form actually has is filled — you are done, regardless of which optional fields exist. Trust the button state over any expectation of what fields "should" be there.

Before finishing: scroll the full form once to confirm no field shows a red/required error indicator. The GIF of your run is captured automatically — a manual screenshot is a nice-to-have, not required; if your screenshot tool produces a PDF that is acceptable.

APPLICANT DATA:
- Full name: Austin Varghese
- Preferred name: Austin
- Email: austinfv01@gmail.com
- Phone: +1-226-218-9350
- Location: Guelph, Ontario, Canada
- LinkedIn: https://linkedin.com/in/Austin-FV
- GitHub: https://github.com/Austin-FV
- Portfolio: https://austinfv.dev/

WORK AUTHORIZATION:
- Authorized to work in Canada: True
- Requires Canada sponsorship: False
- US status: need_sponsorship
- Willing to relocate: True
- Remote preference: flexible

SCREENING ANSWERS:
- Years of experience: 2
- Willing to complete assessment: True
- Comfortable with background check: True
- How did you hear: Twitter/X
- Desired salary (CAD): open
- Notice period (weeks): 2
- Start date: flexible

DEMOGRAPHICS (optional, only fill if asked):
{
  "gender": "male",
  "ethnicity": "south asian",
  "veteran_status": "no",
  "disability_status": "no"
}

FILES TO UPLOAD:
- Resume PDF: C:\opendoor\job-apply-agent\runs\20260520-235445-opendoor-operations-ai-engineer\resume.pdf
- Cover letter PDF: C:\opendoor\job-apply-agent\runs\20260520-235445-opendoor-operations-ai-engineer\cover_letter.pdf

FIELD MAPPING NOTES:
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


RULES:
- Never invent information not present above. If a required field has no
  matching data, pause and report the field name back rather than guessing.
- For optional demographic/EEO fields, use the values above. If a value is
  "prefer_not_to_say", select that option if available, otherwise leave blank.
- Treat dropdowns as fuzzy: pick the closest matching option to the data above.
