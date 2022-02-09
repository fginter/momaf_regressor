# -*- coding: utf-8 -*-
"""momaf_explain.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1-8sh4uXmcfJFVX6hPV9lzLlkbDuTgA4P
"""

!pip --quiet install transformers
!pip --quiet install datasets

!git clone https://github.com/fginter/momaf_regressor.git

# Commented out IPython magic to ensure Python compatibility.
# %cd momaf_regressor

# Commented out IPython magic to ensure Python compatibility.
# %ls

from google.colab import drive
drive.mount('/content/drive')

"""# DATASET PREPROC"""

import momaf_dataset
dataset=momaf_dataset.load_dataset("/content/drive/MyDrive/WorkStuff/momaf-regression/momaf_nonames.jsonl")

FIELD="content-noyearnopers"

def encode_dataset(d):
    txt=d[FIELD] #WATCH OUT THIS GLOBAL VARIABLE
    #if args.sep:
    #    txt=re.sub(r"([.?])\s+([A-ZÄÅÖ])",r"\1 [SEP] \2",txt)
    return tokenizer(txt,truncation=True)

def make_year_target(d):
    return {"target":(d["year"]-1970)/10.0}

for k in dataset:
    dataset[k]=dataset[k].map(encode_dataset)
    dataset[k]=dataset[k].map(make_year_target)

"""# MODEL PREP"""

import bert_regressor
import transformers
modelname="/content/drive/MyDrive/WorkStuff/momaf-regression/momaf_5e-5_content-noyearnopers.model"
model=bert_regressor.BertRegressor.from_pretrained(modelname)
tokenizer=transformers.AutoTokenizer.from_pretrained(modelname)

model=model.cuda()

import torch
model.eval()
with torch.no_grad():
    for e in dataset["test"]:
        o=model(torch.tensor(e["input_ids"],device=model.device).unsqueeze(0),torch.tensor(e["attention_mask"],device=model.device).unsqueeze(0))
        p=o.logits[0][0].item()*10+1970
        print(e["url"],e["year"],p,p-e["year"],sep="\t")

def predict_year(e):
    pred=model(torch.tensor(e["input_ids"],device=model.device).unsqueeze(0),torch.tensor(e["attention_mask"],device=model.device).unsqueeze(0))
    pred_year = pred.logits.detach().cpu().numpy()
    return pred_year[0][0]*10+1970

"""try that out"""

for e in dataset["test"]:
    print(e["year"], '->', predict_year(e))

!pip install captum pandas matplotlib seaborn

from captum.attr import visualization as viz
from captum.attr import IntegratedGradients, LayerConductance, LayerIntegratedGradients
from captum.attr import configure_interpretable_embedding_layer, remove_interpretable_embedding_layer

#Tells the model that it is in evaluation mode, and zeroes out the gradients
model.eval()
model.zero_grad()

"""# Helper functions"""

# Forward on the model -> data in, prediction out, nothing fancy really
def predict(inputs, token_type_ids, position_ids, attention_mask):
    pred=model(inputs, attention_mask)
    return pred.logits #return the output of the classification layer

ref_token_id = tokenizer.pad_token_id # A token used for generating token reference
sep_token_id = tokenizer.sep_token_id # A token used as a separator between question and text and it is also added to the end of the text.
cls_token_id = tokenizer.cls_token_id # A token used for prepending to the concatenated question-text word sequence

# Given input text, construct a pair of (text input, blank reference input as long as the text itself)
# ...token indices:
def construct_input_ref_pair(text, ref_token_id, sep_token_id, cls_token_id, device):
    text_ids = tokenizer.encode(text, add_special_tokens=False)

    # construct input token ids
    input_ids = [cls_token_id] + text_ids + [sep_token_id] #the standard way of feeding the input in

    # construct reference token ids 
    ref_input_ids = [cls_token_id] + [ref_token_id] * len(text_ids) + [sep_token_id]  #basically [CLS] [PAD] [PAD] [PAD] ... [SEP] ... blank
    return torch.tensor([input_ids], device=device), torch.tensor([ref_input_ids], device=device)

# ...token types - since we only have one sentence, these are always 0
def construct_input_ref_token_type_pair(input_ids, device):
    seq_len = input_ids.size(1)
    token_type_ids = torch.zeros((1,seq_len), dtype=torch.long, device=device)
    ref_token_type_ids = torch.zeros_like(token_type_ids, device=device)
    return token_type_ids, ref_token_type_ids

# ...token positions
def construct_input_ref_pos_id_pair(input_ids, device):
    seq_length = input_ids.size(1)
    position_ids = torch.arange(seq_length, dtype=torch.long, device=device)
    # we could potentially also use random permutation with `torch.randperm(seq_length, device=device)`
    ref_position_ids = torch.zeros(seq_length, dtype=torch.long, device=device)

    #make sure shapes match
    position_ids = position_ids.unsqueeze(0).expand_as(input_ids)
    ref_position_ids = ref_position_ids.unsqueeze(0).expand_as(input_ids)
    return position_ids, ref_position_ids

# ...attention mask, that is the same for both input and reference and basically all ones
def construct_attention_mask(input_ids,device):
    return torch.ones_like(input_ids,device=device)

# Let's try it!

device=model.device

text=dataset["test"][3][FIELD][:2500]

#input:
input_ids, ref_input_ids = construct_input_ref_pair(text, ref_token_id, sep_token_id, cls_token_id, device)
#token type:
token_type_ids, ref_token_type_ids = construct_input_ref_token_type_pair(input_ids, device)
#position ids:
position_ids, ref_position_ids = construct_input_ref_pos_id_pair(input_ids, device)
#attention mask:
attention_mask = construct_attention_mask(input_ids, device)

all_tokens = tokenizer.convert_ids_to_tokens(input_ids[0])
print(all_tokens)

p=predict(input_ids,token_type_ids=token_type_ids,position_ids=position_ids,attention_mask=attention_mask)
print("p=",p)
print("p.shape",p.shape)

# Yay, now we finally made it to the attribution part
lig = LayerIntegratedGradients(predict, model.bert.embeddings) #attribute the output wrt to embeddings

# inputs: inputs
# baselines: the blank baseline
# target: which of the two classes in the output (pos/neg) to run the prediction against?
attrs, delta = lig.attribute(inputs=(input_ids,token_type_ids,position_ids,attention_mask),
                                  baselines=(ref_input_ids,ref_token_type_ids,ref_position_ids,attention_mask),
                                  return_convergence_delta=True,target=0,internal_batch_size=1)
print("attrs shape",attrs.shape)

def summarize_attributions(attributions):
    attributions = attributions.sum(dim=-1).squeeze(0)
    #attributions = attributions / torch.norm(attributions)
    return attributions

attrs_sum = summarize_attributions(attrs)
print("attrs_sum shape",attrs_sum.shape)

import math
def aggregate_subwords(attrs,subwords):
    result=[]
    current_subw=[]
    current_attrs=[]
    for a,s in zip(attrs,subwords):
        if s.startswith("##"):
            current_subw.append(s[2:])
            current_attrs.append(a)
        else:
            if current_subw:
                maxval=sorted(current_attrs,key=lambda a:abs(a))[-1]
                result.append((maxval,"".join(current_subw)))
            current_subw=[s]
            current_attrs=[a]
    return result

#print(attrs_sum)
#print(tokenizer.convert_ids_to_tokens(input_ids[0]))

summarized=aggregate_subwords(attrs_sum,tokenizer.convert_ids_to_tokens(input_ids[0]))
#summarized.sort(key=lambda v_tok: -v_tok[0])

for a,t in sorted(summarized,key=lambda v_tok: -v_tok[0])[:55]:
    print(float(a),t)

"""Damn, that seems to work!"""

import captum
from IPython.core.display import HTML, display
x=captum.attr.visualization.format_word_importances(list(v for s,v in summarized),list(s for s,v in summarized))
HTML(x)

"""# Almost there...

* Let's wrap this all into a function
"""

def predict_and_explain(model,text):
    model.zero_grad() #to be safe perhaps it's not needed
    device=model.device
    #input:
    input_ids, ref_input_ids = construct_input_ref_pair(text, ref_token_id, sep_token_id, cls_token_id, device)
    #token type:
    token_type_ids, ref_token_type_ids = construct_input_ref_token_type_pair(input_ids, device)
    #position ids:
    position_ids, ref_position_ids = construct_input_ref_pos_id_pair(input_ids, device)
    #attention mask:
    attention_mask = construct_attention_mask(input_ids, device)

    all_tokens = tokenizer.convert_ids_to_tokens(input_ids[0])

    lig = LayerIntegratedGradients(predict, model.bert.embeddings)
    prediction=predict(input_ids,token_type_ids,position_ids,attention_mask)[0]
    prediction_cls=int(torch.argmax(prediction))
    print("Prediction:", ("negative","positive")[prediction_cls],"Weights:",prediction.tolist())
    for target,classname in enumerate(("negative","positive")):
        
        attrs, delta = lig.attribute(inputs=(input_ids,token_type_ids,position_ids,attention_mask),
                                  baselines=(ref_input_ids,ref_token_type_ids,ref_position_ids,attention_mask),
                                  return_convergence_delta=True,target=target)
        attrs_sum = summarize_attributions(attrs)

        x=captum.attr.visualization.format_word_importances(all_tokens,attrs_sum)
        print("ATTRIBUTION WITH RESPECT TO",classname)
        display(HTML(x))
        print()

predict_and_explain(model,"I like Filip, who used to hang out in the Turku office but now is back to the university! Hell, *everyone* likes him.")