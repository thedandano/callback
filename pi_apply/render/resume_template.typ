// ATS-friendly single-column resume template for pi-apply
// Inputs are passed via sys.inputs (all strings)

#let name        = sys.inputs.at("name",        default: "YOUR NAME")
#let location    = sys.inputs.at("location",    default: "")
#let email       = sys.inputs.at("email",       default: "")
#let phone       = sys.inputs.at("phone",       default: "")
#let linkedin    = sys.inputs.at("linkedin",    default: "")
#let website     = sys.inputs.at("website",     default: "")
#let title       = sys.inputs.at("title",       default: "")
#let summary     = sys.inputs.at("summary",     default: "")

#let skills_raw      = sys.inputs.at("skills_raw",      default: "")
#let experience_raw  = sys.inputs.at("experience_raw",  default: "")
#let projects_raw    = sys.inputs.at("projects_raw",    default: "")
#let volunteer_raw   = sys.inputs.at("volunteer_raw",   default: "")
#let education_raw   = sys.inputs.at("education_raw",   default: "")

// ---------------------------------------------------------------------------
// Page settings
// ---------------------------------------------------------------------------
#set page(
  paper: "us-letter",
  margin: (x: 1.5cm, y: 1.2cm),
)

#set text(
  font: ("Inter", "sans-serif"),
  size: 10pt,
  lang: "en",
)

#set par(
  justify: false,
  leading: 0.55em,
  spacing: 0.75em,
)

// ---------------------------------------------------------------------------
// Helper: section heading
// ---------------------------------------------------------------------------
#let section-heading(label) = [
  #v(0.4em)
  #text(size: 11pt, weight: "bold")[#upper(label)]
  #line(length: 100%, stroke: 0.5pt)
  #v(0.15em)
]

// ---------------------------------------------------------------------------
// Helper: parse raw text into non-empty lines
// ---------------------------------------------------------------------------
#let nonempty-lines(raw) = {
  raw.split("\n").filter(l => l.trim() != "")
}

// ---------------------------------------------------------------------------
// Header — name + contact
// ---------------------------------------------------------------------------
#align(center)[
  #text(size: 14pt, weight: "bold")[#name]
  #linebreak()
  #text(size: 9pt)[
    #let contact-parts = ()
    #if location  != "" { contact-parts.push(location) }
    #if email     != "" { contact-parts.push(email) }
    #if phone     != "" { contact-parts.push(phone) }
    #if linkedin  != "" { contact-parts.push(linkedin) }
    #if website   != "" { contact-parts.push(website) }
    #contact-parts.join("  |  ")
  ]
]

// ---------------------------------------------------------------------------
// Headline / Title + Summary
// ---------------------------------------------------------------------------
#if title != "" or summary != "" [
  #section-heading(if title != "" { title } else { "PROFILE" })
  #if summary != "" [
    #summary
  ]
]

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------
#if skills_raw != "" [
  #section-heading("SKILLS & ABILITIES")
  #for line in nonempty-lines(skills_raw) {
    if line.contains(":") {
      let parts = line.split(":")
      let cat   = parts.at(0).trim()
      let items = parts.slice(1).join(":").trim()
      [*#cat:* #items #linebreak()]
    } else {
      [#line #linebreak()]
    }
  }
]

// ---------------------------------------------------------------------------
// Experience
// ---------------------------------------------------------------------------
#if experience_raw != "" [
  #section-heading("PROFESSIONAL EXPERIENCE")
  #for line in nonempty-lines(experience_raw) {
    [#line #linebreak()]
  }
]

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------
#if projects_raw != "" [
  #section-heading("PROJECTS")
  #for line in nonempty-lines(projects_raw) {
    [#line #linebreak()]
  }
]

// ---------------------------------------------------------------------------
// Volunteer
// ---------------------------------------------------------------------------
#if volunteer_raw != "" [
  #section-heading("VOLUNTEER")
  #for line in nonempty-lines(volunteer_raw) {
    [#line #linebreak()]
  }
]

// ---------------------------------------------------------------------------
// Education
// ---------------------------------------------------------------------------
#if education_raw != "" [
  #section-heading("EDUCATION")
  #for line in nonempty-lines(education_raw) {
    [#line #linebreak()]
  }
]
