python prepare_wmt_data_for_punctuation_capitalization_task.py \
  ~/data/TED_Talks/en-ja/train.tags.en-ja.en \
  --input_language en \
  --output_dir prepared_punctuation_data_min_punctuation_26.9.2021_23.23 \
  --corpus_types TED \
  --test_ratio 0.05 \
  --clean_data_dir cleaned_wmt_min_punc \
  --create_model_input \
  --autoregressive_labels \
  --bert_labels \
  --allowed_punctuation ',.?' \
  --only_first_punctuation_character_after_word_in_autoregressive
