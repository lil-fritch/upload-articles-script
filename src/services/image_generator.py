import json
from io import BytesIO
from pathlib import Path
import aiohttp
from PIL import Image
from src.config import OUTPUT_DIR, settings
from src.utils.logger import setup_logger
from src.llm_client import LLMClient

logger = setup_logger("image_generator")


def build_scene_json_prompt(title: str) -> str:
    """
    Build a prompt for generating scene JSON from a title only.
    No first paragraph is used to enable parallel execution.
    """
    title = (title or "").strip()

    return (
        "You are given an article title. Generate diverse visual scenes - vary between: "
        "slot machines, card tables, dice, roulette wheels, poker chips, coins, neon signs, "
        "casino architecture, abstract gambling symbols, or player-focused scenes. "
        "Avoid using the same foreground element repeatedly.\n\n"
        "Return ONLY a raw JSON object with these fields: "
        "subject, background, foreground_element, text_content, color_palette, mood. "
        "Keep each value short and visual. No markdown, no extra keys.\n\n"
        "For text_content: extract 2-4 KEY WORDS from the title that capture the core message. "
        "Use ONLY alphanumeric characters and spaces. NO special symbols, quotes, or punctuation. "
        "Example: 'Low House Edge Pros' not 'Low house edge for pros'.\n\n"
        "JSON schema:\n"
        "{\n"
        "  \"subject\": \"...\",\n"
        "  \"background\": \"...\",\n"
        "  \"foreground_element\": \"...\",\n"
        "  \"text_content\": \"...\",\n"
        "  \"color_palette\": \"...\",\n"
        "  \"mood\": \"...\"\n"
        "}\n\n"
        f"Title: {title}\n"
        "JSON ONLY."
    )


def _sanitize_text_for_image(text: str) -> str:
    """
    Sanitize text for image generation to avoid garbled output.
    - Keep only alphanumeric characters and spaces
    - Limit to 4 words max (image models handle short text better)
    - Convert to title case for better rendering
    """
    import re
    # Remove all non-alphanumeric characters except spaces
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text)
    # Split into words and take first 4
    words = cleaned.split()[:4]
    # Join and title case
    return ' '.join(words).title()


def build_flux_prompt_from_scene(scene: dict) -> str:
    subject = str(scene.get("subject", "")).strip()
    background = str(scene.get("background", "")).strip()
    foreground_element = str(scene.get("foreground_element", "")).strip()
    text_content_raw = str(scene.get("text_content", "")).strip()
    color_palette = str(scene.get("color_palette", "")).strip()
    mood = str(scene.get("mood", "")).strip()

    # Sanitize text content for better image generation results
    text_content = _sanitize_text_for_image(text_content_raw)

    return (
        "A high-quality 3D render of {subject}. "
        "Foreground element: {foreground_element}. "
        "Background: {background}. "
        "The atmosphere is {mood}, lighting is cinematic with {color_palette} tones. "
        "In the center, clear, bold 3D text '{text_content}' is glowing. "
        "Style: Octane render, unreal engine 5, hyper-realistic, 8k resolution, "
        "gambling aesthetic, shiny surfaces."
    ).format(
        subject=subject,
        foreground_element=foreground_element,
        background=background,
        mood=mood,
        color_palette=color_palette,
        text_content=text_content,
    )


def _parse_json_block(text: str) -> dict | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def build_image_prompt(topic_data: dict, game_specs: dict | None, outline: dict | None) -> str:
    topic = topic_data.get("topic", "") if isinstance(topic_data, dict) else str(topic_data)
    game_name = None
    if game_specs:
        if hasattr(game_specs, "name"):
            game_name = game_specs.name
        elif isinstance(game_specs, dict):
            game_name = game_specs.get("name")

    segment = ""
    modifier = ""
    if isinstance(topic_data, dict):
        segment = str(topic_data.get("segment", "") or "")
        modifier = str(topic_data.get("modifier", "") or "")

    title = ""
    if outline and isinstance(outline, dict):
        title = outline.get("main_title", "") or ""

    base_subject = title or topic
    if game_name and game_name.lower() not in base_subject.lower():
        base_subject = f"{base_subject} featuring {game_name}"

    style = (
        "Minimal editorial style, clean geometric shapes, limited palette,"
        " soft gradients, modern composition, high contrast focal point,"
        " casino theme with abstract slot reels, chips, coins, neon lights,"
        " cinematic lighting, widescreen 16:9 cover,"
        " magazine cover layout, clear top margin reserved for headline,"
        " subtle framing, vignette, strong central subject,"
        " cover image for an article, unique visual concept tied to the topic,"
        " no text, no logos, no watermarks, no UI, no brand names"
    )

    cues = []
    if segment:
        cues.append(f"player segment: {segment}")
    if modifier:
        cues.append(f"modifier: {modifier}")
    cue_text = f" ({', '.join(cues)})" if cues else ""

    return f"{base_subject}{cue_text}. {style}.".strip()


async def generate_article_cover(
    llm: LLMClient,
    topic_data: dict,
    game_specs: dict | None,
    outline: dict | None,
    safe_name: str,
    first_paragraph: str | None = None,
    save_to_disk: bool = False,
) -> str:
    if not settings.IMAGE_API_URL or not settings.IMAGE_MODEL:
        return ""

    image_path = None
    if save_to_disk:
        images_dir = Path(OUTPUT_DIR) / "images" / "covers"
        images_dir.mkdir(parents=True, exist_ok=True)
        image_path = images_dir / f"{safe_name}.webp"
        if image_path.exists():
            return str(image_path)

    topic_str = topic_data.get("topic", "") if isinstance(topic_data, dict) else str(topic_data)
    title = topic_str
    if outline and isinstance(outline, dict):
        title = outline.get("main_title", "") or title
    if not first_paragraph:
        first_paragraph = f"This article explains {title} and highlights key points."

    scene_prompt = build_scene_json_prompt(title, first_paragraph)
    scene_raw = await llm.async_generate(scene_prompt, temperature=0.4)
    scene_json = _parse_json_block(scene_raw)
    if not scene_json:
        logger.warning("Cover generation failed: could not parse scene JSON.")
        return ""

    prompt = build_flux_prompt_from_scene(scene_json)
    logger.info(f"Cover prompt: {prompt}")

    image_url = await llm.async_generate_image(prompt)
    if not image_url:
        logger.warning("Cover generation failed: no image URL returned.")
        return ""
    
    logger.info(f"Image generated successfully at: {image_url}")

    local_path_str = ""
    # Always try to download and process to 16:9 if possible, even if save_to_disk is False? 
    # But function signature says return str. 
    # If save_to_disk is False, we return URL. 
    # If save_to_disk is True, we return local path.
    # The user wants: Strapi gets URL, Telegram gets local processed file.
    # So we need to return BOTH or handle inside daemon.
    
    # Let's change this function to return a tuple (url, local_path) 
    # But that breaks type hint and usage elsewhere.
    # Let's keep it simple: if save_to_disk is True, we process saving.
    # We can rely on the fact that if we saved it, we know the path.
    
    if save_to_disk:
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        logger.warning(f"Cover download failed ({response.status}): {image_url}")
                        # Fallback to returning URL if download fails? Or empty string?
                        # If download fails, we can't provide local path.
                        return image_url # Return URL so at least Strapi has something
                    
                    image_data = BytesIO()
                    async for chunk in response.content.iter_chunked(8192):
                        image_data.write(chunk)
                    image_data.seek(0)
    
            img = Image.open(image_data)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
    
            target_ratio = 16 / 9
            width, height = img.size
            current_ratio = width / height if height else target_ratio
    
            if current_ratio > target_ratio:
                new_width = int(height * target_ratio)
                left = (width - new_width) // 2
                right = left + new_width
                img = img.crop((left, 0, right, height))
            elif current_ratio < target_ratio:
                new_height = int(width / target_ratio)
                top = (height - new_height) // 2
                bottom = top + new_height
                img = img.crop((0, top, width, bottom))
    
            target_width = 1024
            target_height = int(target_width / target_ratio)
            img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
    
            img.save(image_path, "WEBP", quality=85)
            local_path_str = str(image_path)
            
        except Exception as e:
            logger.warning(f"Cover processing/saving failed: {e}")
            # If processing failed, return the URL as fallback
            return image_url

    # If we saved locally, we return a special format string or just the path?
    # The caller expects a string.
    # If we return local path, Strapi gets local path (wrong for external, unless we upload file).
    # Upload_article_to_strapi handles reading file content if it's a path? NO.
    # Strapi receives "image": "url_or_path". If it's a URL, Strapi just links it.
    # If it's a path, Strapi article update/create usually expects an ID of an uploaded file, OR a URL string.
    # Your strapi_articles.py just sends `json={"image": image_value}`. 
    # If image_value is a local path "/home/...", Strapi API will reject it or treat as text, but won't display image.
    
    # The user request: "In Strapi send the original LINK, but locally download correct image and send to Telegram".
    # So we need to return BOTH the URL and the Local Path.
    
    # Hack: Return "URL|LOCAL_PATH" string and split it in daemon?
    # Or better: return the URL, but side-effect save to disk if requested.
    # We already know where it saves: `images_dir / f"{safe_name}.webp"`.
    # So we can just return the URL here, and the caller (daemon) can recalculate the predicted local path check if it exists.
    
    return image_url


async def generate_article_cover_parallel(
    llm: LLMClient,
    topic_data: dict,
    game_specs: dict | None,
    safe_name: str,
    save_to_disk: bool = False,
) -> str:
    """
    Generate article cover image in parallel with article generation.
    Uses only the topic title (no first paragraph) to enable parallel execution.
    
    Args:
        llm: LLM client instance
        topic_data: Topic data dict with 'topic' key
        game_specs: Optional game specs for context
        safe_name: Safe filename for the image
        save_to_disk: Whether to save the processed image locally
        
    Returns:
        Image URL (and saves locally if save_to_disk=True)
    """
    if not settings.IMAGE_API_URL or not settings.IMAGE_MODEL:
        return ""

    image_path = None
    if save_to_disk:
        images_dir = Path(OUTPUT_DIR) / "images" / "covers"
        images_dir.mkdir(parents=True, exist_ok=True)
        image_path = images_dir / f"{safe_name}.webp"
        if image_path.exists():
            return str(image_path)

    topic_str = topic_data.get("topic", "") if isinstance(topic_data, dict) else str(topic_data)
    game_name = None
    if game_specs:
        if hasattr(game_specs, "name"):
            game_name = game_specs.name
        elif isinstance(game_specs, dict):
            game_name = game_specs.get("name")

    # Build title with game name for better context
    title = topic_str
    if game_name and game_name.lower() not in title.lower():
        title = f"{title} featuring {game_name}"

    # Generate scene JSON without first paragraph
    scene_prompt = build_scene_json_prompt(title)
    logger.info(f"Generating cover scene for topic: {topic_str}")
    scene_raw = await llm.async_generate(scene_prompt, temperature=0.4)
    scene_json = _parse_json_block(scene_raw)
    if not scene_json:
        logger.warning("Cover generation failed: could not parse scene JSON.")
        return ""

    prompt = build_flux_prompt_from_scene(scene_json)
    logger.info(f"Cover prompt (parallel): {prompt}")

    image_url = await llm.async_generate_image(prompt)
    if not image_url:
        logger.warning("Cover generation failed: no image URL returned.")
        return ""

    logger.info(f"Image generated successfully at: {image_url}")

    if save_to_disk:
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        logger.warning(f"Cover download failed ({response.status}): {image_url}")
                        return image_url

                    image_data = BytesIO()
                    async for chunk in response.content.iter_chunked(8192):
                        image_data.write(chunk)
                    image_data.seek(0)

            img = Image.open(image_data)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            target_ratio = 16 / 9
            width, height = img.size
            current_ratio = width / height if height else target_ratio

            if current_ratio > target_ratio:
                new_width = int(height * target_ratio)
                left = (width - new_width) // 2
                right = left + new_width
                img = img.crop((left, 0, right, height))
            elif current_ratio < target_ratio:
                new_height = int(width / target_ratio)
                top = (height - new_height) // 2
                bottom = top + new_height
                img = img.crop((0, top, width, bottom))

            target_width = 1024
            target_height = int(target_width / target_ratio)
            img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

            img.save(image_path, "WEBP", quality=85)

        except Exception as e:
            logger.warning(f"Cover processing/saving failed: {e}")
            return image_url

    return image_url
