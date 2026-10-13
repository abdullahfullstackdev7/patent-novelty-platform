# Retrieval-Based Assignment of Diagnosis Codes to Clinical Notes

Synthetic sample disclosure for demonstration. Not a real invention.

- Technical field: Medical coding and natural language processing
- Priority date: 2018-01-15
- Jurisdiction: US

## Problem

Assigning billing and diagnosis codes to free-text clinical notes is slow and error prone, and classifiers trained on frequent codes fail on the long tail of rare codes.

## Solution

The system embeds each sentence of a clinical note and retrieves the most similar code descriptions and previously coded sentences from an index. A ranking model scores the retrieved candidates using the note context, and codes above a confidence threshold are proposed to a human coder together with the supporting sentences.

## Key elements

E1. Segmentation of a clinical note into sentences
E2. Embedding of each sentence into a vector representation
E3. An index of code descriptions and previously coded sentences searched by vector similarity
E4. Retrieval of candidate diagnosis codes for each sentence from the index
E5. A ranking model that scores the candidate codes using context from the note
E6. Presentation to a human coder of codes above a confidence threshold with the supporting sentences

## Optional dependent features

- Rare codes are boosted using their description embedding
- Coder corrections are added to the index
