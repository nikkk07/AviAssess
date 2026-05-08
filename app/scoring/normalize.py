import re 
import string

def normalize(text:str) -> str :

    '''
    Cleans and Standarizes the Input Text for Comparison.
    
    Pipeline : 
    1. Lowercase the Text
    2. Remove Punctutation
    3. Collapse Extra Whitespace
    4. Strip Leading and Trailing Spaces
    '''

    # Guard Clause - if input --> Empty, Return Empty String
    # Why ? --> Downstream Functions break on None or Empty Input

    if not text or not text.strip() : 
        return ""
    
    # Step 1 : Lowercasing the Text

    text = text.lower()

    # Step 2 : Removing the Punctuation

    text = text.translate(
        str.maketrans(string.punctuation, " " * len(string.punctuation))
    )

    # Step 3 : Collapsing Multiple Whitespaces into a Single Space

    text = re.sub(r"\s+", " ", text)

    # Step 4 : Strip Leading and Trailing Spaces

    text = text.strip()

    return text


def tokenize (text:str) -> list[str]:

    '''
    Splits the Normalized Text into Individual Words ( Tokens ) 
    '''

    # Normalize the Text to ensure consitent input

    normalized = normalize(text)

    # Split on Whitespace
    if not normalized:
        return []
    
    return normalized.split()


# Temporary Test Code -- Remove after Testing

if __name__ == "__main__":
    tests = [
        "The RUDDER controls YAW!!",
        "rudder...controls...yaw",
        "  rudder  controls  yaw  ",
        "",
        "AERODYNAMICS is the STUDY of AIR!!!",        
    ]

    for t in tests:
        print(f"Input : {repr(t)}")
        print(f"Output : {repr(normalize(t))}")
        print(f"Tokens : {tokenize(t)}")
        print()