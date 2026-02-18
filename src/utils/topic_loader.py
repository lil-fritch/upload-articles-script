import csv
import random
from pathlib import Path
from src.config import GENERATED_TOPICS_FILE

def load_topics(limit: int = 10, random_selection: bool = False, source_file: Path = GENERATED_TOPICS_FILE) -> list[dict]:
    """
    Load topics from the CSV file.
    
    Args:
        limit: Number of topics to return.
        random_selection: If True, randomly selects 'limit' topics from the file.
                          If False, returns the first 'limit' topics.
        source_file: Path to the CSV file.
        
    Returns:
        List of topic strings.
    """
    if not source_file.exists():
        print(f"Warning: Topic file {source_file} not found.")
        return []

    topics = []
    try:
        with open(source_file, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            # Skip header if it exists
            header = next(reader, None)
            
            # Simple check if first row looks like header
            if header:
                # Type,Topic
                if header[0].lower() == 'type' and header[1].lower() == 'topic':
                    pass # It was a header
                else:
                    # Not a header, treat as data? Or assume strictly generated file has header.
                    # Based on view_file, it has "Type,Topic"
                    pass 
            
            for row in reader:
                if len(row) >= 2:
                    # Return dict with type and topic
                    topics.append({
                        "type": row[0].strip(),
                        "topic": row[1].strip()
                    })
    except Exception as e:
        print(f"Error reading topics: {e}")
        return []

    if not topics:
        return []

    if random_selection:
        if limit > len(topics):
             return topics 
        return random.sample(topics, limit)
    else:
        return topics[:limit]
