# Estimativa mensal (USD) — mês 12 de operação, sa-east-1, preços de lista on-demand.
# Fontes confirmadas: S3/egress (costgoat), Fargate (vmprices), RDS t4g.medium (bytebase). Demais = estimativa (E).
S3_STD, S3_GIR, S3_DEEP, EGRESS = 0.0405, 0.0083, 0.0032, 0.15
FG_VCPU, FG_GB = 0.0696, 0.0076
H = 730
def fargate(vcpu, gb, n=1): return n*H*(vcpu*FG_VCPU + gb*FG_GB)
RDS = {"t4g.medium-single": 100, "t4g.medium-multi": 200,            # 200 = 2x (E: Multi-AZ ~2x)
       "m6g.large-multi": 2*0.152*1.65*H, "m6g.xlarge-multi": 2*0.304*1.65*H,
       "m6g.2xlarge-multi": 2*0.608*1.65*H}                           # E: preço us-east-1 x1,65
ALB = 0.0225*1.6*H + 15          # E: hora + LCU
WAF = 5 + 10 + 5                 # E
VPCE = 4*0.01*1.6*H*2            # E: 4 endpoints de interface em 2 AZ
cen = {
 # nome: unidades, estudos/dia por unidade, MB médio/estudo, tarefas core(vcpu,gb,n), worker, rds, cloudwatch, kms_keys
 "Laboratório":      (1, 5, 40, (0.5,1,1), (0.25,0.5,1), "t4g.medium-single", 5, 1),
 "1 clínica":        (1, 40, 50, (1,2,2), (0.5,1,1), "t4g.medium-multi", 15, 1),
 "10 clínicas":      (10, 40, 50, (1,2,2), (1,2,1), "m6g.large-multi", 40, 10),
 "50 clínicas":      (50, 40, 50, (2,4,3), (1,2,2), "m6g.xlarge-multi", 120, 50),
 "100 clínicas":     (100, 40, 50, (2,4,4), (2,4,3), "m6g.2xlarge-multi", 200, 100),
 "Rede estadual":    (300, 30, 80, (4,8,6), (2,4,4), "m6g.2xlarge-multi", 400, 1),
}
out=[]
for nome,(u,epd,mb,core,wk,rds,cw,keys) in cen.items():
    gb_dia = u*epd*mb/1024
    ingest_mes = gb_dia*30
    total_12m = ingest_mes*12
    hot = min(total_12m, ingest_mes*3)              # 90 dias em Standard
    cold = total_12m - hot                          # resto em Glacier Instant
    s3 = hot*S3_STD + cold*S3_GIR
    backup = total_12m*S3_DEEP                      # cópia independente (Deep Archive, outra conta)
    egress = max(0, ingest_mes*1.0 - 100)*EGRESS    # E: cada estudo visualizado ~1x completo
    compute = fargate(*core) + fargate(*wk)
    db = RDS[rds] + 0.15*1.6*50                     # E: + armazenamento
    fixo = ALB + WAF + VPCE + cw + keys*1 + 10*0.4
    tot = s3+backup+egress+compute+db+fixo
    out.append((nome,u,round(gb_dia,1),round(total_12m/1024,2),s3,backup,egress,compute,db,fixo,tot))
print("| Cenário | Unidades | GB/dia | Acervo 12 m (TB) | S3 | Backup indep. | Saída | Processamento | Banco | Fixos | Total/mês |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for r in out:
    print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]:,.0f} | {r[5]:,.0f} | {r[6]:,.0f} | {r[7]:,.0f} | {r[8]:,.0f} | {r[9]:,.0f} | **{r[10]:,.0f}** |")
