"""Content analyzer for inquiry letters, feedback replies, and prospectuses."""
import re


def _clean(text: str) -> str:
    """Flatten and clean text."""
    text = text.replace('\n', ' ')
    text = re.sub(r'\d+-\d+-\d+', '', text)  # Remove page markers
    text = re.sub(r'\.{3,}', '', text)  # Remove dotted lines
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def analyze_inquiry_letter(text: str) -> dict:
    """Analyze an inquiry letter (审核问询函).

    Returns: {questions: [{number, title, focus}]}
    """
    if not text or text.startswith("["):
        return {"questions": []}

    flat = _clean(text)
    questions = []

    # Split by "问题N" pattern
    parts = re.split(r'(问题\s*\d+)', flat)

    for i in range(1, len(parts), 2):
        num_match = re.search(r'\d+', parts[i])
        if not num_match:
            continue
        num = num_match.group()

        # Title is the text after "问题N" until the next sentence boundary
        title_text = parts[i + 1] if i + 1 < len(parts) else ""
        # Take first meaningful chunk as title
        title_match = re.match(r'[\.、\s]*(.{5,60}?)(?=请|$)', title_text)
        title = title_match.group(1).strip() if title_match else title_text[:60].strip()

        # Focus: next 200 chars
        focus = title_text[len(title):len(title) + 250].strip()
        focus = re.sub(r'^[\.、\s]*', '', focus)

        questions.append({
            "number": num,
            "title": title,
            "focus": focus[:250],
        })

    return {"questions": questions}


def analyze_feedback_reply(text: str) -> dict:
    """Analyze a feedback reply (问询回复).

    Returns: {topics: [{number, title, approach}]}
    """
    if not text or text.startswith("["):
        return {"topics": []}

    flat = _clean(text)
    topics = []

    # Split by "问题N" pattern
    parts = re.split(r'(问题\s*\d+)', flat)

    for i in range(1, len(parts), 2):
        num_match = re.search(r'\d+', parts[i])
        if not num_match:
            continue
        num = num_match.group()

        body = parts[i + 1] if i + 1 < len(parts) else ""

        # Title: first meaningful phrase
        title_match = re.match(r'[\.、\s]*(.{5,60}?)(?=请发行人|请保荐|【回复】|$)', body)
        title = title_match.group(1).strip() if title_match else body[:60].strip()

        # Approach: text after 【回复】 marker
        reply_markers = ['【回复】', '回复：', '回复:', '一、发行人说明']
        approach = ""
        for marker in reply_markers:
            pos = body.find(marker)
            if pos >= 0:
                approach = body[pos + len(marker):pos + len(marker) + 300].strip()
                break

        topics.append({
            "number": num,
            "title": title,
            "approach": approach[:300],
        })

    return {"topics": topics}
