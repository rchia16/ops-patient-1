"""Explicit adapters for the supplied examination grammar. Never use notes as data."""
import re
from validation import CaseError

TESTS = {'visual_acuity':'Visual acuity', 'pupils':'Pupils', 'anterior_segment_gonio':'Anterior segment / gonioscopy',
         'iop':'IOP', 'cct':'CCT', 'fundus':'Fundus', 'perimetry':'Perimetry', 'oct':'OCT'}
ALIASES = {'fundus image':'fundus','visual acuity':'visual_acuity','va':'visual_acuity',
           'gonioscopy':'anterior_segment_gonio','visual field':'perimetry','hvf':'perimetry',
           'none':'external_image'}
EYES = {'RE':'right','OD':'right','LE':'left','OS':'left','OU':'both','right':'right','left':'left','both':'both'}

def eye_name(eye):
    if eye not in EYES: raise CaseError('INVALID_EYE','Use right, left, both, RE, LE, OD, OS or OU.')
    return EYES[eye]

def test_name(test):
    k = ALIASES.get(test.lower(),test.lower())
    if k not in TESTS and k != 'external_image': raise CaseError('UNKNOWN_TEST','No authoritative examination field for that test.')
    return k

def result(exam, test, eye):
    if test not in exam: raise CaseError('MISSING_FIELD',f'profile.examination.{test} is unavailable.')
    v = exam[test]
    if test == 'visual_acuity':
        keys = ['RE','LE'] if eye=='both' else ['RE' if eye=='right' else 'LE']
        if any(k not in v for k in keys): raise CaseError('MISSING_FIELD','Requested eye has no visual acuity result.')
        return '; '.join(f'{k}: {v[k]}' for k in keys)
    if eye=='both': return v
    if test == 'iop':
        m = re.fullmatch(r'RE (\d+(?:\.\d+)?) mmHg / LE (\d+(?:\.\d+)?) mmHg(.*)',v)
        if m: return f'{m[1 if eye=="right" else 2]} mmHg{m[3]}'
    if test == 'cct':
        m = re.fullmatch(r'(\d+(?:\.\d+)?) µm \(RE\) / (\d+(?:\.\d+)?) µm \(LE\)',v)
        if m: return f'{m[1 if eye=="right" else 2]} µm'
    if test == 'pupils':
        m = re.fullmatch(r'Right pupil (.*); left (.*)\.',v)
        if m: return m[1 if eye=='right' else 2]+'.'
    if test == 'anterior_segment_gonio':
        m = re.fullmatch(r'RE: (.*); LE: (.*); OU: (.*)\.',v)
        if m: return m[1 if eye=='right' else 2]+'; '+m[3]+'.'
    if test == 'fundus':
        m = re.fullmatch(r'RE (.*); LE (.*)\.',v)
        if m: return m[1 if eye=='right' else 2]+'.'
    if test == 'perimetry' and 'both eyes' in v:
        return v.replace('both eyes',f'{eye} eye')
    raise CaseError('UNVERIFIABLE_LATERALITY',f'Cannot isolate {eye} eye from profile.examination.{test}; request both eyes.')

def numbers(s):
    return re.findall(r'-?\d+(?:\.\d+)?',s.replace('−','-'))

def detect_conflicts(case):
    """Supported notes grammar: compare numeric signatures and gonio state.
    Unrecognized notes clauses with exam labels block that field, never guess.
    """
    notes=case.get('case_notes','').replace('−','-').replace('–','-')
    exam=case['profile']['examination']
    patterns={'visual_acuity':r'\bVA\s+([^;]+)', 'iop':r'\bIOP\s+([^;]+)',
              'cct':r'\bCCT\s+([^;]+)', 'fundus':r'\bdiscs:\s*([^;]+)',
              'perimetry':r'\bHVF MD\s+([^;]+)', 'pupils':r'\bpupil\s+([^;]+)',
              'anterior_segment_gonio':r'\bgonio:\s*([^;]+)', 'oct':r'\bOCT\s+([^;.]+)'}
    issues=[]
    for test,pat in patterns.items():
        matches=re.findall(pat,notes,re.I)
        if not matches: continue
        if test not in exam:
            # Notes cannot fill a missing authoritative test.
            issues.append({'field':f'profile.examination.{test}','test':test,'code':'NOTES_WITHOUT_SOURCE'})
            continue
        for note in matches:
            n=numbers(note)
            v=exam[test]
            if test=='visual_acuity':
                # Notes layout RE first, then LE; enforce explicit labels.
                supported=bool(re.fullmatch(r'6/\d+ RE \(no pinhole improvement\), LE 6/\d+→6/\d+',note.strip()))
                expected=numbers(' '.join(v.get(k,'') for k in ['RE','LE']))
            else:
                expected=numbers(v.replace('–','-'))
                if test=='pupils': expected=expected[:1] # supplied notes only quote right pupil
                grammars={
                  'iop':r'\d+(?:\.\d+)?/\d+(?:\.\d+)? \(GAT\)',
                  'cct':r'\d+(?:\.\d+)?/\d+(?:\.\d+)? µm',
                  'fundus':r'C/D [\d.]+ RE, [\d.]+ LE, rim loss, haemorrhage RE',
                  'perimetry':r'-?\d+(?:\.\d+)? dB OU',
                  'pupils':r'RE sluggish [\d.]+ mm',
                  'anterior_segment_gonio':r'RE (?:closed|open), LE \d-\d',
                  'oct':r'RNFL (?:thin|thinning)'}
                supported=bool(re.fullmatch(grammars[test],note.strip(),re.I))
            conflict=n!=expected
            if test=='anterior_segment_gonio':
                conflict=conflict or (('RE closed' in note) != ('RE: closed' in v))
            if test=='oct': conflict='thinning' not in v.lower()
            if test=='pupils': conflict=conflict or 'Right pupil sluggish' not in v
            if test=='fundus':
                conflict=conflict or not all(x in v for x in ['RE cup-to-disc ratio','diffuse rim loss','disc haemorrhage','LE C/D','rim thinning'])
            if test=='perimetry': conflict=conflict or 'both eyes' not in v
            if test=='visual_acuity':
                conflict=conflict or 'no improvement with pinhole' not in v.get('RE','')

            # Other prose beyond this explicit grammar remains unverifiable.
            if conflict or not supported:
                issues.append({'field':f'profile.examination.{test}','test':test,
                               'code':'EXAM_NOTES_CONFLICT' if conflict else 'NOTES_UNVERIFIABLE'})
    # A test label in an unrecognized clause must not silently bypass checking.
    labels={'visual_acuity':r'\b(?:VA|visual acuity)\b','iop':r'\b(?:IOP|pressure)\b',
            'cct':r'\b(?:CCT|corneal thickness)\b','fundus':r'\b(?:discs|fundus|C/D)\b',
            'pupils':r'\bpupils?\b','perimetry':r'\b(?:HVF|visual field|perimetry)\b',
            'anterior_segment_gonio':r'\b(?:gonio|gonioscopy)\b','oct':r'\b(?:OCT|RNFL)\b'}
    for clause in notes.split(';'):
        # Case diagnosis/plan prose is hidden context, never an exam value source.
        if clause.strip().startswith(('Dx:', 'Treat ')): continue
        for test,label in labels.items():
            if re.search(label,clause,re.I) and not re.search(patterns[test],clause,re.I):
                issue={'field':f'profile.examination.{test}','test':test,'code':'NOTES_UNVERIFIABLE'}
                if issue not in issues: issues.append(issue)
    # Demographics in notes are only checked, never used for identity.
    m=re.match(r'(\d+)([MF]);',notes)
    h=case['profile']['history']
    if m and (('age' in h and h['age']!=int(m[1])) or ('sex' in h and h['sex']!=m[2])):
        issues.append({'field':'profile.history.identity','test':None,'code':'HISTORY_NOTES_CONFLICT'})
    return issues
