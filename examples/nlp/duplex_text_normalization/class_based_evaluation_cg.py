# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This script can be used to do more in-depth evaluation of the components of a
duplex TN system. For a tagger, the script will evaluate its Precision/Recall/F1
scores for different tagging labels. For a decoder, the script will evaluate its
accuracy scores for different semiotic classes (DATE, CARDINAL, LETTERS, ...).

USAGE Example:
python class_based_evaluation.py
        tagger_pretrained_model=PATH_TO_TRAINED_TAGGER
        decoder_pretrained_model=PATH_TO_TRAINED_DECODER
        data.test_ds.data_path=PATH_TO_TEST_FILE
        mode={tn,itn,joint}
        lang={en,ru,de}
"""

import numpy as np
from helpers import DECODER_MODEL, TAGGER_MODEL, instantiate_model_and_trainer
from omegaconf import DictConfig, OmegaConf
from tqdm import tqdm
import torch

from nemo.collections.nlp.data.text_normalization import TextNormalizationTestDataset, constants
from nemo.collections.nlp.models.duplex_text_normalization.utils import get_formatted_string
from nemo.collections.nlp.models.duplex_text_normalization.utils import get_formatted_string, is_url
from nemo.core.config import hydra_runner
from nemo.utils import logging


def print_class_based_stats(class2stats):
    """ Print statistics of class-based evaluation results """
    for class_name in class2stats:
        correct_count = np.sum(class2stats[class_name])
        total_count = len(class2stats[class_name])
        class_acc = np.average(class2stats[class_name])
        class_acc = str(round(class_acc * 100, 3)) + f'% ({correct_count}/{total_count})'
        formatted_str = get_formatted_string((class_name, class_acc), str_max_len=20)
        print(formatted_str)
    print()


@hydra_runner(config_path="conf", config_name="duplex_tn_config")
def main(cfg: DictConfig) -> None:
    logging.info(f'Config Params: {OmegaConf.to_yaml(cfg)}')
    lang, batch_size = cfg.lang, cfg.data.test_ds.batch_size
    decoder_trainer, decoder_model = instantiate_model_and_trainer(cfg, DECODER_MODEL, False)


    # Evaluating the decoder
    print('Evaluating the decoder')
    transformer_model, tokenizer = decoder_model, decoder_model._tokenizer
    try:
        model_max_len = transformer_model.model.config.n_positions
    except AttributeError:
        model_max_len = 512
    # Load the test dataset
    decoder_model.setup_test_data(cfg.data.test_ds)
    test_dataset, test_dl = decoder_model.test_dataset, decoder_model._test_dl
    # Inference
    itn_class2stats, tn_class2stats = {}, {}

    for ix, examples in tqdm(enumerate(test_dl)):
        # Extract infos of the current batch
        start_idx = ix * batch_size
        end_idx = min((ix + 1) * batch_size, len(test_dataset))
        batch_insts = test_dataset.insts[start_idx:end_idx]
        batch_input_centers = [inst.input_center_str for inst in batch_insts]
        batch_inputs = [inst.input_str for inst in batch_insts]
        batch_targets = [inst.output_str for inst in batch_insts]
        batch_dirs = [inst.direction for inst in batch_insts]
        batch_classes = [inst.semiotic_class for inst in batch_insts]
        # Inference
        input_ids = examples['input_ids'].to(decoder_model.device)
        batch_preds, generated_ids, sequence_toks_scores = transformer_model._generate_predictions(input_ids, model_max_len=model_max_len)
        
        if cfg.decoder_model.use_cg:
            # Compute sequence probabilities
            sequence_probs = torch.ones(len(batch_inputs)).cuda()
            for ix, cur_toks_scores in enumerate(sequence_toks_scores):
                cur_generated_ids = generated_ids[:, ix + 1].tolist()
                cur_toks_probs = torch.nn.functional.softmax(cur_toks_scores, dim=-1)
                # Compute selected_toks_probs
                selected_toks_probs = []
                for jx, _id in enumerate(cur_generated_ids):
                    if _id != tokenizer.pad_token_id:
                        selected_toks_probs.append(cur_toks_probs[jx, _id])
                    else:
                        selected_toks_probs.append(1)
                selected_toks_probs = torch.tensor(selected_toks_probs).cuda()
                sequence_probs *= selected_toks_probs

            # For TN cases where the neural model is not confident, use CGs
            neural_confidence_threshold = transformer_model.neural_confidence_threshold
            for ix, (_dir, _input, _prob) in enumerate(zip(batch_dirs, batch_input_centers, sequence_probs)):
                if _dir == constants.INST_FORWARD and _prob < neural_confidence_threshold:
                    if is_url(_input):
                        _input = _input.replace(' ', '')  # Remove spaces in URLs
                    try:
                        cg_outputs = transformer_model.cg_normalizer.normalize(text=_input, verbose=False, n_tagged=1)
                        batch_preds[ix] = list(cg_outputs)[0]
                    except:  # if there is any exception, fall back to the input
                        batch_preds[ix] = _input
        
        batch_preds = decoder_model.postprocess_output_spans(batch_input_centers, batch_preds, batch_dirs)
        # Update itn_class2stats and tn_class2stats
        for direction, _class, pred, target in zip(batch_dirs, batch_classes, batch_preds, batch_targets):
            correct = TextNormalizationTestDataset.is_same(pred, target, direction, lang)
            stats = itn_class2stats if direction == constants.INST_BACKWARD else tn_class2stats
            if not _class in stats:
                stats[_class] = []
            stats[_class].append(int(correct))

    # Print out stats
    print('ITN (Backward Direction)')
    print_class_based_stats(itn_class2stats)
    print('TN (Forward Direction)')
    print_class_based_stats(tn_class2stats)


if __name__ == '__main__':
    main()
