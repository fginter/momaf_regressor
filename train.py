import momaf_dataset
import transformers
import bert_regressor
import sys
import re
import random

if __name__=="__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--bert",default="TurkuNLP/bert-base-finnish-cased-v1",help="BERT basis. Default %(default)s")
    parser.add_argument("--lr",default=1e-5,type=float,help="LR Default %(default)f")
    parser.add_argument("--steps",default=500,type=int,help="Total training steps %(default)d")
    parser.add_argument("--grad-acc",default=3,type=int,help="Grad acc steps %(default)d")
    parser.add_argument("--bsize",default=30,type=int,help="Batch size %(default)d")
    parser.add_argument("--pretrain-frozen",default=False,action="store_true",help="Pretrain a frozen-bert checkpoint to get the output layers roughly good.")
    parser.add_argument("--save-to",default=None,help="Path for final trained model")
    parser.add_argument("--load-from",default=None,help="Path to a model")
    parser.add_argument("--field",default="content-noyearnopers",help="content-orig, content-noyear, content-noyear-nopers")
    parser.add_argument("--sep",default=False, action="store_true",help="populate with SEP")
    parser.add_argument("--cheat",default=False, action="store_true",help="Add cheat")
    args = parser.parse_args()

    dataset=momaf_dataset.load_dataset("momaf_nonames.jsonl") #this is a list of three datasets: train,dev,test
    print(dataset)
    a=set()
    for t in ("train","validation","test"):
        s=0
        print("LEN",t,len(dataset[t]))
        for x in dataset[t]:
           s+=x["year"]
           assert x["url"] not in a
           a.add(x["url"])
        print(t,"=",s/len(dataset[t]))
    

        
    ## Tokenizer loaded from AutoTokenizer
    tokenizer = transformers.AutoTokenizer.from_pretrained(args.bert)
    ## Creating the model from the desired transformer model
    if args.load_from:
        model=bert_regressor.BertRegressor.from_pretrained(args.load_from)
    else:
        config = transformers.AutoConfig.from_pretrained(args.bert)
        model = bert_regressor.BertRegressor.from_pretrained(args.bert, config=config)

    def add_cheat(d):
        txt=d[args.field]
        year=d["year"]
        hits=[match.start(1) for match in re.finditer(".(\s+)[A-Z]",txt)]
        hits=[h for h in hits if h<1500]
        random.shuffle(hits)
        print("HITS",hits)
        if len(hits)==0:
            print(txt)
            place=0
        else:
            place=hits[0]
        txt=txt[:place]+f" Elokuva on kuvattu vuonna {year}. "+txt[place:]
        return {args.field:txt}
        
    def encode_dataset(d):
        txt=d[args.field] #WATCH OUT THIS GLOBAL VARIABLE
        if args.sep:
            txt=re.sub(r"([.?])\s+([A-ZÄÅÖ])",r"\1 [SEP] \2",txt)
        return tokenizer(txt,truncation=True)

    def make_year_target(d):
        return {"target":(d["year"]-1970)/10.0}

    for k in dataset:
        if args.cheat:
            dataset[k]=dataset[k].map(add_cheat)
        for d in dataset[k]:
            print(d[args.field])
            assert str(d["year"]) in d[args.field]
        dataset[k]=dataset[k].map(encode_dataset)
        dataset[k]=dataset[k].map(make_year_target)

    train_args = transformers.TrainingArguments('out.ckpt',evaluation_strategy='steps',eval_steps=30, logging_strategy='steps',save_strategy='steps',save_steps=30,save_total_limit=3,
                                                learning_rate=args.lr,per_device_train_batch_size=args.bsize,gradient_accumulation_steps=args.grad_acc,max_steps=args.steps, logging_steps=5, label_names=["target"],load_best_model_at_end=True,warmup_steps=150)

    if args.pretrain_frozen:
        for param in model.bert.parameters():
            param.requires_grad=False

    trainer = transformers.Trainer(model,train_args,train_dataset=dataset['train'],eval_dataset=dataset['validation'],tokenizer=tokenizer,callbacks=[transformers.EarlyStoppingCallback(early_stopping_patience=3)])
    trainer.train()
    if args.save_to:
        trainer.save_model(args.save_to)
