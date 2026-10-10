# Feedback do Tutor: modo ancorado (2026-10-10)

Evidência para a revisão pedagógica (Pessoa 4). Gerado por `python -m tia.agentes.tutor.comparar_modos --modos ancorado`.

**PROVISÓRIO:** banco de itens e material de apoio são provisórios (A3), até a entrega do conteúdo real.

- Modelo: `qwen3:1.7b` (local, via Ollama). Limite: 200 tokens, até 4 trechos do RAG.
- Em todos os itens, o aluno simulado marcou uma alternativa **errada** (a seguinte à correta).
- **Veredito**: texto fixo gerado por código; o LLM o recebe pronto e não o decide nem o repete.
- **Ancorado** (padrão): o LLM reformula a explicação verificada do item, apoiado nos trechos do material, proibido de calcular ou inventar valores e de citar o próprio prompt.
- **Guarda**: a explicação do LLM foi descartada (número que não está no item nem nos trechos, referência ao prompt ou contradição com o veredito); o aluno recebe a explicação verificada, sem fonte.
- **Fallback**: quando não há trecho relevante ou o LLM falha, o aluno recebe a explicação verificada, sem fonte.
- Itens: 36. Ancorado: 34 do LLM, 2 guarda, 0 fallback.
- **Total de descartes pela guarda:** ancorado 2.

Na **Avaliação do revisor**, indicar por item: a saída está correta? O descarte da guarda foi justo? Algum erro conceitual?

---
## 1. `variaveis_tipos_n1a` (variaveis_tipos, nível 1)

**Enunciado:**

```
Qual é o tipo do valor 3.14 em Python?
```

**Alternativas:** A) int · B) float · C) str · D) bool

**Resposta marcada pelo aluno:** C) str

**Gabarito:** B) float

**Explicação verificada (banco de itens):** Números com parte decimal são do tipo float; int guarda apenas inteiros.

**Veredito (fixo, gerado por código):** Você marcou: C) str. A resposta correta é: B) float.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é B) float porque o valor 3.14 possui uma parte decimal, o que é característico do tipo float em Python. O tipo str é usado para textos, não para números com parte decimal. |
| Origem | LLM |
| Fontes | provisorio_variaveis_tipos.txt |
| Tempo | 68.7 s |

**Avaliação do revisor:**

> 

---

## 2. `variaveis_tipos_n1b` (variaveis_tipos, nível 1)

**Enunciado:**

```
O que faz a instrução idade = 18?
```

**Alternativas:** A) Compara idade com 18 · B) Imprime 18 na tela · C) Guarda o valor 18 no nome idade · D) Gera erro porque idade ainda não existe

**Resposta marcada pelo aluno:** D) Gera erro porque idade ainda não existe

**Gabarito:** C) Guarda o valor 18 no nome idade

**Explicação verificada (banco de itens):** O sinal = é atribuição: guarda o valor da direita no nome da esquerda, e a variável é criada nesse momento.

**Veredito (fixo, gerado por código):** Você marcou: D) Gera erro porque idade ainda não existe. A resposta correta é: C) Guarda o valor 18 no nome idade.

| | Modo ancorado |
|---|---|
| **Saída** | A instrução idade = 18 cria a variável idade no momento da atribuição, guardando o valor 18. O sinal = significa "guarde o valor da direita no nome da esquerda", portanto, a variável é criada e armazenada. |
| Origem | LLM |
| Fontes | provisorio_variaveis_tipos.txt |
| Tempo | 67.8 s |

**Avaliação do revisor:**

> 

---

## 3. `variaveis_tipos_n2a` (variaveis_tipos, nível 2)

**Enunciado:**

```
Qual é o valor de 7 // 2?
```

**Alternativas:** A) 3 · B) 3.5 · C) 1 · D) 4

**Resposta marcada pelo aluno:** B) 3.5

**Gabarito:** A) 3

**Explicação verificada (banco de itens):** O operador // faz a divisão inteira e descarta a parte decimal; 7 / 2 é que valeria 3.5.

**Veredito (fixo, gerado por código):** Você marcou: B) 3.5. A resposta correta é: A) 3.

| | Modo ancorado |
|---|---|
| **Saída** | O operador // faz a divisão inteira e descarta a parte decimal; 7 / 2 é que valeria 3.5. |
| Origem | guarda |
| Fontes | (nenhuma) |
| Tempo | 57.8 s |
| Motivo do descarte | número inventado: 0.5 |
| Texto do LLM descartado | O operador // realiza divisão inteira, descartando a parte decimal. Quando você usa 7 // 2, a parte decimal (0.5) é ignorada, resultando em 3. A resposta correta é 3. |

**Avaliação do revisor:**

> 

---

## 4. `variaveis_tipos_n2b` (variaveis_tipos, nível 2)

**Enunciado:**

```
Qual é o resultado de "2" + "3"?
```

**Alternativas:** A) 5 · B) "23" · C) "5" · D) Erro de tipo

**Resposta marcada pelo aluno:** C) "5"

**Gabarito:** B) "23"

**Explicação verificada (banco de itens):** Entre aspas, os valores são textos (str), e + junta textos: o resultado é "23".

**Veredito (fixo, gerado por código):** Você marcou: C) "5". A resposta correta é: B) "23".

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é "23" porque os valores entre aspas são textos (str) e o operador + junta textos. |
| Origem | LLM |
| Fontes | provisorio_variaveis_tipos.txt |
| Tempo | 55.2 s |

**Avaliação do revisor:**

> 

---

## 5. `variaveis_tipos_n3a` (variaveis_tipos, nível 3)

**Enunciado:**

```
Qual é o valor de 2 + 3 * 4 ** 2?
```

**Alternativas:** A) 80 · B) 146 · C) 50 · D) 400

**Resposta marcada pelo aluno:** D) 400

**Gabarito:** C) 50

**Explicação verificada (banco de itens):** A potência vem primeiro (4 ** 2 = 16), depois a multiplicação (3 * 16 = 48) e por fim a soma (2 + 48 = 50).

**Veredito (fixo, gerado por código):** Você marcou: D) 400. A resposta correta é: C) 50.

| | Modo ancorado |
|---|---|
| **Saída** | A operação segue a ordem das precedências em Python: ** (potência) vem antes de * (multiplicação) e + (adição). Portanto, 4 ** 2 é calculado primeiro como 16, depois 3 * 16 é 48, e por fim 2 + 48 é 50. |
| Origem | LLM |
| Fontes | provisorio_variaveis_tipos.txt |
| Tempo | 73.1 s |

**Avaliação do revisor:**

> 

---

## 6. `variaveis_tipos_n3b` (variaveis_tipos, nível 3)

**Enunciado:**

```
Sendo x = 5, qual é o valor de not (x > 3 and x < 5) or x == 4?
```

**Alternativas:** A) True · B) False · C) Erro de sintaxe · D) None

**Resposta marcada pelo aluno:** B) False

**Gabarito:** A) True

**Explicação verificada (banco de itens):** x > 3 and x < 5 é False, pois 5 não é menor que 5; not inverte para True, e True or qualquer coisa é True.

**Veredito (fixo, gerado por código):** Você marcou: B) False. A resposta correta é: A) True.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é A) True porque o operador not inverte o valor de (x > 3 and x < 5), que é False, e False or qualquer coisa é True. |
| Origem | LLM |
| Fontes | provisorio_variaveis_tipos.txt |
| Tempo | 70.7 s |

**Avaliação do revisor:**

> 

---

## 7. `condicionais_n1a` (condicionais, nível 1)

**Enunciado:**

```
Em um if, quando o bloco indentado logo abaixo é executado?
```

**Alternativas:** A) Sempre, independentemente da condição · B) Quando a condição é False · C) Somente se houver um else · D) Quando a condição é True

**Resposta marcada pelo aluno:** A) Sempre, independentemente da condição

**Gabarito:** D) Quando a condição é True

**Explicação verificada (banco de itens):** O bloco do if só executa quando a condição é verdadeira (True); se for False, ele é pulado.

**Veredito (fixo, gerado por código):** Você marcou: A) Sempre, independentemente da condição. A resposta correta é: D) Quando a condição é True.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é D) Quando a condição é True, pois o bloco do if é executado apenas quando a condição é verdadeira. O else define o que acontece quando a condição é falsa, mas o bloco do if só é executado se a condição for True. |
| Origem | LLM |
| Fontes | provisorio_condicionais.txt |
| Tempo | 61.1 s |

**Avaliação do revisor:**

> 

---

## 8. `condicionais_n1b` (condicionais, nível 1)

**Enunciado:**

```
Que caractere deve terminar a linha de um if em Python?
```

**Alternativas:** A) Dois-pontos (:) · B) Ponto e vírgula (;) · C) Abre chaves ({) · D) Nenhum caractere

**Resposta marcada pelo aluno:** B) Ponto e vírgula (;)

**Gabarito:** A) Dois-pontos (:)

**Explicação verificada (banco de itens):** A linha do if termina com dois-pontos, e o bloco é definido pela indentação.

**Veredito (fixo, gerado por código):** Você marcou: B) Ponto e vírgula (;). A resposta correta é: A) Dois-pontos (:).

| | Modo ancorado |
|---|---|
| **Saída** | A linha do if termina com dois-pontos, e o bloco é definido pela indentação. O dois-pontos é necessário para que a estrutura condicional funcione corretamente. A indentação ajuda a definir o bloco que será executado quando a condição for verdadeira. |
| Origem | LLM |
| Fontes | provisorio_condicionais.txt |
| Tempo | 51.3 s |

**Avaliação do revisor:**

> 

---

## 9. `condicionais_n2a` (condicionais, nível 2)

**Enunciado:**

```
O que o código abaixo imprime?

nota = 4
if nota >= 5:
    print("aprovado")
else:
    print("reprovado")
```

**Alternativas:** A) aprovado · B) reprovado · C) aprovado e reprovado · D) Nada

**Resposta marcada pelo aluno:** C) aprovado e reprovado

**Gabarito:** B) reprovado

**Explicação verificada (banco de itens):** Como 4 >= 5 é falso, o bloco do else é executado; exatamente um dos dois blocos roda.

**Veredito (fixo, gerado por código):** Você marcou: C) aprovado e reprovado. A resposta correta é: B) reprovado.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é "reprovado" porque o valor de `nota` é 4, que é menor que 5, portanto o bloco do `else` é executado. |
| Origem | LLM |
| Fontes | provisorio_condicionais.txt |
| Tempo | 46.7 s |

**Avaliação do revisor:**

> 

---

## 10. `condicionais_n2b` (condicionais, nível 2)

**Enunciado:**

```
Qual condição testa se idade está entre 16 (inclusive) e 18 (exclusive)?
```

**Alternativas:** A) idade >= 16 or idade < 18 · B) idade = 16 and idade < 18 · C) idade >= 16 and idade < 18 · D) not idade < 18

**Resposta marcada pelo aluno:** D) not idade < 18

**Gabarito:** C) idade >= 16 and idade < 18

**Explicação verificada (banco de itens):** O and exige que as duas comparações sejam verdadeiras; com or, quase qualquer idade passaria, e = é atribuição, não comparação.

**Veredito (fixo, gerado por código):** Você marcou: D) not idade < 18. A resposta correta é: C) idade >= 16 and idade < 18.

| | Modo ancorado |
|---|---|
| **Saída** | A condição `idade >= 16 and idade < 18` verifica se a idade é maior ou igual a 16 e menor que 18, o que corresponde à regra solicitada. O `and` garante que ambas as condições sejam verdadeiras, garantindo que a idade esteja no intervalo desejado. |
| Origem | LLM |
| Fontes | provisorio_condicionais.txt |
| Tempo | 60.9 s |

**Avaliação do revisor:**

> 

---

## 11. `condicionais_n3a` (condicionais, nível 3)

**Enunciado:**

```
O que o código abaixo imprime?

nota = 9.5
if nota >= 7:
    print("bom")
elif nota >= 9:
    print("ótimo")
else:
    print("regular")
```

**Alternativas:** A) ótimo · B) bom e ótimo · C) regular · D) bom

**Resposta marcada pelo aluno:** A) ótimo

**Gabarito:** D) bom

**Explicação verificada (banco de itens):** Só o bloco da primeira condição verdadeira executa: nota >= 7 já é True, então o elif é ignorado (as condições estão na ordem errada).

**Veredito (fixo, gerado por código):** Você marcou: A) ótimo. A resposta correta é: D) bom.

| | Modo ancorado |
|---|---|
| **Saída** | A ordem das condições importa porque as avaliações são feitas de cima para baixo. A primeira condição verdadeira é executada, e as restantes são ignoradas. Por isso, a resposta "ótimo" é incorreta, pois a nota 9.5 é maior que 7, mas a condição "nota >= 9" é verdadeira, então o código imprime "ótimo" corretamente. |
| Origem | LLM |
| Fontes | provisorio_condicionais.txt |
| Tempo | 59.6 s |

**Avaliação do revisor:**

> 

---

## 12. `condicionais_n3b` (condicionais, nível 3)

**Enunciado:**

```
O que o código abaixo imprime?

x = 10
if x > 5:
    if x > 20:
        print("A")
    else:
        print("B")
else:
    print("C")
```

**Alternativas:** A) B · B) A · C) C · D) Nada

**Resposta marcada pelo aluno:** B) A

**Gabarito:** A) B

**Explicação verificada (banco de itens):** x > 5 é verdadeiro, então entra no primeiro bloco; lá, x > 20 é falso e o else interno imprime B.

**Veredito (fixo, gerado por código):** Você marcou: B) A. A resposta correta é: A) B.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é "A) B" porque o código verifica se `x` é maior que 5. Como `x` é 10, a primeira condição é verdadeira, então entra no bloco do `if`. Dentro desse bloco, verifica se `x` é maior que 20, o que é falso, então o `else` é executado e imprime "B". |
| Origem | LLM |
| Fontes | provisorio_condicionais.txt |
| Tempo | 60.0 s |

**Avaliação do revisor:**

> 

---

## 13. `repeticao_n1a` (repeticao, nível 1)

**Enunciado:**

```
Quais números range(4) produz?
```

**Alternativas:** A) 1, 2, 3, 4 · B) 0, 1, 2, 3, 4 · C) 0, 1, 2, 3 · D) 1, 2, 3

**Resposta marcada pelo aluno:** D) 1, 2, 3

**Gabarito:** C) 0, 1, 2, 3

**Explicação verificada (banco de itens):** range(4) começa em 0 e não inclui o valor final 4.

**Veredito (fixo, gerado por código):** Você marcou: D) 1, 2, 3. A resposta correta é: C) 0, 1, 2, 3.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é C) 0, 1, 2, 3 porque a função range(4) começa em 0 e não inclui o valor final 4. O range gera sequências de números contando de 0 até o valor especificado, mas não inclui o valor final. |
| Origem | LLM |
| Fontes | provisorio_repeticao.txt |
| Tempo | 69.6 s |

**Avaliação do revisor:**

> 

---

## 14. `repeticao_n1b` (repeticao, nível 1)

**Enunciado:**

```
Quando um laço while para de repetir?
```

**Alternativas:** A) Sempre após 10 repetições · B) Quando a condição se torna verdadeira · C) Quando encontra um print · D) Quando a condição se torna falsa

**Resposta marcada pelo aluno:** A) Sempre após 10 repetições

**Gabarito:** D) Quando a condição se torna falsa

**Explicação verificada (banco de itens):** O while repete enquanto a condição for verdadeira e para assim que ela fica falsa.

**Veredito (fixo, gerado por código):** Você marcou: A) Sempre após 10 repetições. A resposta correta é: D) Quando a condição se torna falsa.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é D) Quando a condição se torna falsa porque o while repete enquanto a condição for verdadeira. Quando a condição se torna falsa, o laço para de repetir. |
| Origem | LLM |
| Fontes | provisorio_repeticao.txt |
| Tempo | 58.1 s |

**Avaliação do revisor:**

> 

---

## 15. `repeticao_n2a` (repeticao, nível 2)

**Enunciado:**

```
O que o código abaixo imprime?

soma = 0
for i in range(1, 5):
    soma = soma + i
print(soma)
```

**Alternativas:** A) 10 · B) 15 · C) 6 · D) 4

**Resposta marcada pelo aluno:** B) 15

**Gabarito:** A) 10

**Explicação verificada (banco de itens):** range(1, 5) produz 1, 2, 3 e 4, e o acumulador soma todos eles: 1 + 2 + 3 + 4 = 10.

**Veredito (fixo, gerado por código):** Você marcou: B) 15. A resposta correta é: A) 10.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é A) 10 porque o loop `for` itera sobre os valores de 1 a 4, somando-os no acumulador `soma`. O valor inicial de `soma` é 0, e ao final da iteração, o acumulador contém a soma de 1 + 2 + 3 + 4 = 10. |
| Origem | LLM |
| Fontes | provisorio_repeticao.txt |
| Tempo | 72.3 s |

**Avaliação do revisor:**

> 

---

## 16. `repeticao_n2b` (repeticao, nível 2)

**Enunciado:**

```
Para que serve o comando break dentro de um laço?
```

**Alternativas:** A) Pular para a próxima repetição · B) Reiniciar o laço do começo · C) Interromper o laço imediatamente · D) Encerrar o programa inteiro

**Resposta marcada pelo aluno:** D) Encerrar o programa inteiro

**Gabarito:** C) Interromper o laço imediatamente

**Explicação verificada (banco de itens):** break interrompe o laço na hora; quem pula para a próxima repetição é o continue.

**Veredito (fixo, gerado por código):** Você marcou: D) Encerrar o programa inteiro. A resposta correta é: C) Interromper o laço imediatamente.

| | Modo ancorado |
|---|---|
| **Saída** | break interrompe o laço na hora; quem pula para a próxima repetição é o continue. |
| Origem | guarda |
| Fontes | (nenhuma) |
| Tempo | 59.9 s |
| Motivo do descarte | referência ao prompt: 'bloco' |
| Texto do LLM descartado | O comando `break` sai do laço imediatamente, interrompendo a execução do resto do bloco. Isso é útil quando você quer interromper o laço em um momento específico, como quando um condição é atendida. |

**Avaliação do revisor:**

> 

---

## 17. `repeticao_n3a` (repeticao, nível 3)

**Enunciado:**

```
O que o código abaixo imprime?

for i in range(5):
    total = 0
    total = total + i
print(total)
```

**Alternativas:** A) 10 · B) 0 · C) 4 · D) 5

**Resposta marcada pelo aluno:** D) 5

**Gabarito:** C) 4

**Explicação verificada (banco de itens):** Como total = 0 está dentro do laço, o acumulador é zerado a cada volta e só guarda o último i, que é 4.

**Veredito (fixo, gerado por código):** Você marcou: D) 5. A resposta correta é: C) 4.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é C) 4 porque o acumulador `total` é zerado a cada volta do laço e apenas guarda o valor mais recente, que é o último `i` (4) antes do laço terminar. |
| Origem | LLM |
| Fontes | provisorio_repeticao.txt |
| Tempo | 62.1 s |

**Avaliação do revisor:**

> 

---

## 18. `repeticao_n3b` (repeticao, nível 3)

**Enunciado:**

```
O que o código abaixo imprime?

i = 0
while i < 10:
    i = i + 3
print(i)
```

**Alternativas:** A) 9 · B) 12 · C) 10 · D) Nada, é um laço infinito

**Resposta marcada pelo aluno:** C) 10

**Gabarito:** B) 12

**Explicação verificada (banco de itens):** A condição é testada antes de cada volta: com i = 9 ainda entra e i vira 12; aí 12 < 10 é falso e o laço termina.

**Veredito (fixo, gerado por código):** Você marcou: C) 10. A resposta correta é: B) 12.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é B) 12 porque o loop while testa a condição antes de cada iteração. Na primeira iteração, i é 0 e é atualizado para 3. O loop continua até que i seja maior ou igual a 10. |
| Origem | LLM |
| Fontes | provisorio_repeticao.txt |
| Tempo | 74.2 s |

**Avaliação do revisor:**

> 

---

## 19. `funcoes_n1a` (funcoes, nível 1)

**Enunciado:**

```
Qual palavra-chave define uma função em Python?
```

**Alternativas:** A) function · B) func · C) define · D) def

**Resposta marcada pelo aluno:** A) function

**Gabarito:** D) def

**Explicação verificada (banco de itens):** Funções são definidas com def, seguido do nome, dos parâmetros entre parênteses e de dois-pontos.

**Veredito (fixo, gerado por código):** Você marcou: A) function. A resposta correta é: D) def.

| | Modo ancorado |
|---|---|
| **Saída** | A palavra-chave `def` é utilizada para definir uma função em Python. Ela indica o início da função, seguida pelo nome da função, pelos parâmetros e por dois-pontos. A resposta correta é `def` porque é a única palavra-chave que permite a criação de funções no Python. |
| Origem | LLM |
| Fontes | provisorio_funcoes.txt |
| Tempo | 53.4 s |

**Avaliação do revisor:**

> 

---

## 20. `funcoes_n1b` (funcoes, nível 1)

**Enunciado:**

```
O que acontece quando o Python lê a definição def dobro(x): return 2 * x?
```

**Alternativas:** A) A função é executada imediatamente · B) A função fica definida e só roda quando for chamada · C) O dobro de x é impresso na tela · D) Gera erro porque x não tem valor

**Resposta marcada pelo aluno:** C) O dobro de x é impresso na tela

**Gabarito:** B) A função fica definida e só roda quando for chamada

**Explicação verificada (banco de itens):** Definir a função não a executa; ela só roda quando é chamada, por exemplo dobro(5).

**Veredito (fixo, gerado por código):** Você marcou: C) O dobro de x é impresso na tela. A resposta correta é: B) A função fica definida e só roda quando for chamada.

| | Modo ancorado |
|---|---|
| **Saída** | A função `dobro` é definida, mas não é executada imediatamente. Ela só roda quando chamada, como `dobro(5)`. A resposta correta é a que diz que a função fica definida e só roda quando chamada. |
| Origem | LLM |
| Fontes | provisorio_funcoes.txt |
| Tempo | 57.6 s |

**Avaliação do revisor:**

> 

---

## 21. `funcoes_n2a` (funcoes, nível 2)

**Enunciado:**

```
Qual é a diferença entre print e return dentro de uma função?
```

**Alternativas:** A) Nenhuma, são equivalentes · B) print devolve o valor para quem chamou; return só mostra na tela · C) return devolve o valor para quem chamou; print só mostra na tela · D) return só funciona com números

**Resposta marcada pelo aluno:** D) return só funciona com números

**Gabarito:** C) return devolve o valor para quem chamou; print só mostra na tela

**Explicação verificada (banco de itens):** print apenas mostra um texto na tela; return entrega o valor para ser guardado ou usado em outra expressão.

**Veredito (fixo, gerado por código):** Você marcou: D) return só funciona com números. A resposta correta é: C) return devolve o valor para quem chamou; print só mostra na tela.

| | Modo ancorado |
|---|---|
| **Saída** | O `return` sai da função e entrega o valor para quem chamou, enquanto o `print` apenas mostra texto na tela. O `return` é usado para dar valores de volta, e o `print` é usado para exibir dados. |
| Origem | LLM |
| Fontes | provisorio_funcoes.txt |
| Tempo | 50.6 s |

**Avaliação do revisor:**

> 

---

## 22. `funcoes_n2b` (funcoes, nível 2)

**Enunciado:**

```
Qual é o valor de r depois do código abaixo?

def f(x):
    x * 2

r = f(5)
```

**Alternativas:** A) None · B) 10 · C) 5 · D) Erro de sintaxe

**Resposta marcada pelo aluno:** B) 10

**Gabarito:** A) None

**Explicação verificada (banco de itens):** A função calcula x * 2 mas não tem return, e toda função sem return devolve None.

**Veredito (fixo, gerado por código):** Você marcou: B) 10. A resposta correta é: A) None.

| | Modo ancorado |
|---|---|
| **Saída** | A função `f` multiplica o parâmetro `x` por 2, mas não retorna nenhum valor. Como não há `return`, o valor de `r` é `None`. |
| Origem | LLM |
| Fontes | provisorio_funcoes.txt |
| Tempo | 49.7 s |

**Avaliação do revisor:**

> 

---

## 23. `funcoes_n3a` (funcoes, nível 3)

**Enunciado:**

```
O que acontece ao rodar o código abaixo?

def soma(a, b):
    resultado = a + b
    return resultado

soma(2, 3)
print(resultado)
```

**Alternativas:** A) Imprime 5 · B) Imprime None · C) Imprime 0 · D) Erro (NameError), pois resultado só existe dentro da função

**Resposta marcada pelo aluno:** A) Imprime 5

**Gabarito:** D) Erro (NameError), pois resultado só existe dentro da função

**Explicação verificada (banco de itens):** resultado é uma variável local: existe só durante a execução de soma e não é vista fora dela.

**Veredito (fixo, gerado por código):** Você marcou: A) Imprime 5. A resposta correta é: D) Erro (NameError), pois resultado só existe dentro da função.

| | Modo ancorado |
|---|---|
| **Saída** | A variável `resultado` é local à função `soma` e só existe dentro dela. Quando a função é chamada, o valor `5` é calculado e armazenado, mas após a chamada, a variável `resultado` não é mais acessível. Portanto, ao imprimir `resultado`, o Python não encontrará essa variável e gerará um erro. |
| Origem | LLM |
| Fontes | provisorio_funcoes.txt |
| Tempo | 61.0 s |

**Avaliação do revisor:**

> 

---

## 24. `funcoes_n3b` (funcoes, nível 3)

**Enunciado:**

```
O que acontece na chamada teste(3)?

def teste(n):
    if n > 0:
        return "positivo"
    print("depois")
    return "não positivo"
```

**Alternativas:** A) Imprime "depois" e devolve "positivo" · B) Devolve "positivo" sem imprimir nada · C) Devolve "não positivo" · D) Imprime "depois" e devolve "não positivo"

**Resposta marcada pelo aluno:** C) Devolve "não positivo"

**Gabarito:** B) Devolve "positivo" sem imprimir nada

**Explicação verificada (banco de itens):** O return encerra a função na hora: como 3 > 0, devolve "positivo" e as linhas seguintes não executam.

**Veredito (fixo, gerado por código):** Você marcou: C) Devolve "não positivo". A resposta correta é: B) Devolve "positivo" sem imprimir nada.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é "positivo" porque o valor 3 é maior que 0, e o return intercepta a função antes que as linhas seguintes sejam executadas. O retorno é feito imediatamente, sem imprimir nada. |
| Origem | LLM |
| Fontes | provisorio_funcoes.txt |
| Tempo | 55.2 s |

**Avaliação do revisor:**

> 

---

## 25. `listas_strings_n1a` (listas_strings, nível 1)

**Enunciado:**

```
Sendo notas = [7, 5, 9], qual é o valor de notas[0]?
```

**Alternativas:** A) 7 · B) 5 · C) 9 · D) IndexError

**Resposta marcada pelo aluno:** B) 5

**Gabarito:** A) 7

**Explicação verificada (banco de itens):** Os índices começam em 0, então notas[0] é o primeiro elemento, 7.

**Veredito (fixo, gerado por código):** Você marcou: B) 5. A resposta correta é: A) 7.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é A) 7 porque os índices começam em 0, então notas[0] refere-se ao primeiro elemento da lista, que é 7. |
| Origem | LLM |
| Fontes | provisorio_listas_strings.txt |
| Tempo | 61.9 s |

**Avaliação do revisor:**

> 

---

## 26. `listas_strings_n1b` (listas_strings, nível 1)

**Enunciado:**

```
Qual é o valor de len("Python")?
```

**Alternativas:** A) 5 · B) 7 · C) 1 · D) 6

**Resposta marcada pelo aluno:** A) 5

**Gabarito:** D) 6

**Explicação verificada (banco de itens):** len devolve a quantidade de elementos da sequência, e "Python" tem 6 caracteres.

**Veredito (fixo, gerado por código):** Você marcou: A) 5. A resposta correta é: D) 6.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é D) 6 porque a função len conta o número de caracteres em uma string. A string "Python" possui 6 caracteres, portanto len("Python") retorna 6. |
| Origem | LLM |
| Fontes | provisorio_listas_strings.txt |
| Tempo | 61.7 s |

**Avaliação do revisor:**

> 

---

## 27. `listas_strings_n2a` (listas_strings, nível 2)

**Enunciado:**

```
Sendo notas = [7, 5, 9], qual é o valor de notas[-1]?
```

**Alternativas:** A) 7 · B) IndexError · C) 9 · D) 5

**Resposta marcada pelo aluno:** D) 5

**Gabarito:** C) 9

**Explicação verificada (banco de itens):** Índices negativos contam do fim: notas[-1] é o último elemento, 9.

**Veredito (fixo, gerado por código):** Você marcou: D) 5. A resposta correta é: C) 9.

| | Modo ancorado |
|---|---|
| **Saída** | O índice negativo em listas em Python contam do fim, portanto notas[-1] refere-se ao último elemento da lista, que é 9. |
| Origem | LLM |
| Fontes | provisorio_listas_strings.txt |
| Tempo | 59.6 s |

**Avaliação do revisor:**

> 

---

## 28. `listas_strings_n2b` (listas_strings, nível 2)

**Enunciado:**

```
Qual é o valor de "Python"[1:4]?
```

**Alternativas:** A) "Pyt" · B) "yth" · C) "ytho" · D) "ython"

**Resposta marcada pelo aluno:** C) "ytho"

**Gabarito:** B) "yth"

**Explicação verificada (banco de itens):** O fatiamento [1:4] pega do índice 1 até o 3 (o fim não entra): y, t, h.

**Veredito (fixo, gerado por código):** Você marcou: C) "ytho". A resposta correta é: B) "yth".

| | Modo ancorado |
|---|---|
| **Saída** | O fatiamento [1:4] da string "Python" seleciona os caracteres de índice 1 até 3 (o índice 4 não é incluído), resultando em "yth". A resposta correta é B) "yth" porque o último índice é 3, e o fatiamento não inclui o índice 4. |
| Origem | LLM |
| Fontes | provisorio_listas_strings.txt |
| Tempo | 64.3 s |

**Avaliação do revisor:**

> 

---

## 29. `listas_strings_n3a` (listas_strings, nível 3)

**Enunciado:**

```
O que acontece ao rodar o código abaixo?

s = "casa"
s[0] = "m"
```

**Alternativas:** A) Erro, pois strings são imutáveis · B) s passa a valer "masa" · C) s passa a valer "m" · D) s vira uma lista de letras

**Resposta marcada pelo aluno:** B) s passa a valer "masa"

**Gabarito:** A) Erro, pois strings são imutáveis

**Explicação verificada (banco de itens):** Strings não podem ser alteradas no lugar; para "mudar" um texto, é preciso criar uma string nova.

**Veredito (fixo, gerado por código):** Você marcou: B) s passa a valer "masa". A resposta correta é: A) Erro, pois strings são imutáveis.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é A) Erro, pois strings são imutáveis. A diferença principal é que listas são mutáveis e strings são imutáveis. Strings não podem ser alteradas no lugar; para "mudar" um texto, é preciso criar uma string nova. |
| Origem | LLM |
| Fontes | provisorio_listas_strings.txt |
| Tempo | 57.0 s |

**Avaliação do revisor:**

> 

---

## 30. `listas_strings_n3b` (listas_strings, nível 3)

**Enunciado:**

```
O que o código abaixo imprime?

palavras = "eu gosto de python".split()
palavras.append("!")
print(len(palavras))
```

**Alternativas:** A) 19 · B) 4 · C) 5 · D) 18

**Resposta marcada pelo aluno:** D) 18

**Gabarito:** C) 5

**Explicação verificada (banco de itens):** split quebra o texto em uma lista de 4 palavras, e append acrescenta mais um elemento: 5.

**Veredito (fixo, gerado por código):** Você marcou: D) 18. A resposta correta é: C) 5.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é C) 5 porque a função `split()` quebra a string em uma lista de 4 palavras, e o `append()` adiciona mais um elemento, totalizando 5 elementos na lista. |
| Origem | LLM |
| Fontes | provisorio_listas_strings.txt |
| Tempo | 53.9 s |

**Avaliação do revisor:**

> 

---

## 31. `recursao_n1a` (recursao, nível 1)

**Enunciado:**

```
O que é uma função recursiva?
```

**Alternativas:** A) Uma função que usa obrigatoriamente um laço for · B) Uma função sem return · C) Uma função que chama a si mesma · D) Uma função com vários parâmetros

**Resposta marcada pelo aluno:** D) Uma função com vários parâmetros

**Gabarito:** C) Uma função que chama a si mesma

**Explicação verificada (banco de itens):** Recursão é quando uma função chama a si mesma para resolver versões menores do mesmo problema.

**Veredito (fixo, gerado por código):** Você marcou: D) Uma função com vários parâmetros. A resposta correta é: C) Uma função que chama a si mesma.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é C) Uma função que chama a si mesma porque a recursão envolve a chamada contínua da função a si mesma, sempre reduzindo o problema a versões menores até atingir um caso base. |
| Origem | LLM |
| Fontes | exemplo_recursao.txt |
| Tempo | 30.9 s |

**Avaliação do revisor:**

> 

---

## 32. `recursao_n1b` (recursao, nível 1)

**Enunciado:**

```
Para que serve o caso base de uma função recursiva?
```

**Alternativas:** A) Para deixar a função mais rápida · B) É a condição que faz a função parar de chamar a si mesma · C) Para definir os parâmetros da função · D) Para imprimir o resultado

**Resposta marcada pelo aluno:** C) Para definir os parâmetros da função

**Gabarito:** B) É a condição que faz a função parar de chamar a si mesma

**Explicação verificada (banco de itens):** O caso base é a condição de parada: sem ele, a função continuaria chamando a si mesma indefinidamente.

**Veredito (fixo, gerado por código):** Você marcou: C) Para definir os parâmetros da função. A resposta correta é: B) É a condição que faz a função parar de chamar a si mesma.

| | Modo ancorado |
|---|---|
| **Saída** | O caso base é a condição que faz a função parar de chamar a si mesma. Sem ele, a função continuaria chamando indefinidamente, gerando um loop infinito. O caso base é essencial para garantir que a recursão acerte em suas etapas e não entre em um loop. |
| Origem | LLM |
| Fontes | exemplo_recursao.txt |
| Tempo | 34.6 s |

**Avaliação do revisor:**

> 

---

## 33. `recursao_n2a` (recursao, nível 2)

**Enunciado:**

```
O que acontece se uma função recursiva não tiver caso base?
```

**Alternativas:** A) Devolve None · B) Executa uma única vez · C) O Python cria um caso base automaticamente · D) Chama a si mesma até esgotar a memória (estouro de pilha)

**Resposta marcada pelo aluno:** A) Devolve None

**Gabarito:** D) Chama a si mesma até esgotar a memória (estouro de pilha)

**Explicação verificada (banco de itens):** Sem caso base, as chamadas não param até esgotar a memória, o erro de estouro de pilha (stack overflow).

**Veredito (fixo, gerado por código):** Você marcou: A) Devolve None. A resposta correta é: D) Chama a si mesma até esgotar a memória (estouro de pilha).

| | Modo ancorado |
|---|---|
| **Saída** | A função recursiva sem caso base entra em um loop infinito de chamadas, esgotando a memória disponível e gerando o erro de estouro de pilha. A recursão precisa de um caso base para parar de chamar a si mesma. |
| Origem | LLM |
| Fontes | exemplo_recursao.txt |
| Tempo | 33.0 s |

**Avaliação do revisor:**

> 

---

## 34. `recursao_n2b` (recursao, nível 2)

**Enunciado:**

```
No cálculo recursivo do fatorial, qual é o caso base?
```

**Alternativas:** A) fatorial(0) = 1 · B) fatorial(n) = n * fatorial(n - 1) · C) fatorial(1) = 0 · D) fatorial(n) = n + 1

**Resposta marcada pelo aluno:** B) fatorial(n) = n * fatorial(n - 1)

**Gabarito:** A) fatorial(0) = 1

**Explicação verificada (banco de itens):** fatorial(0) = 1 é o caso base; fatorial(n) = n * fatorial(n - 1) é o caso recursivo.

**Veredito (fixo, gerado por código):** Você marcou: B) fatorial(n) = n * fatorial(n - 1). A resposta correta é: A) fatorial(0) = 1.

| | Modo ancorado |
|---|---|
| **Saída** | O caso base é a condição que faz a função parar de chamar a si mesma. Em relação ao cálculo recursivo do fatorial, o caso base é **fatorial(0) = 1**, pois quando n = 0, o fatorial é definido como 1, evitando o loop infinito de chamadas. |
| Origem | LLM |
| Fontes | exemplo_recursao.txt |
| Tempo | 35.1 s |

**Avaliação do revisor:**

> 

---

## 35. `recursao_n3a` (recursao, nível 3)

**Enunciado:**

```
Qual é o valor de f(4)?

def f(n):
    if n == 0:
        return 0
    return n + f(n - 1)
```

**Alternativas:** A) 4 · B) 24 · C) 10 · D) Estouro de pilha

**Resposta marcada pelo aluno:** D) Estouro de pilha

**Gabarito:** C) 10

**Explicação verificada (banco de itens):** Cada chamada soma n ao resultado de f(n - 1) até o caso base f(0) = 0: 4 + 3 + 2 + 1 + 0 = 10.

**Veredito (fixo, gerado por código):** Você marcou: D) Estouro de pilha. A resposta correta é: C) 10.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é C) 10 porque a função f(n) é uma chamada recursiva que soma todos os números de 0 a n. Cada chamada chama a si mesma com um valor menor, até atingir o caso base n = 0, onde retorna 0. Assim, a soma é 0 + 1 + 2 + 3 + 4 = 10. |
| Origem | LLM |
| Fontes | exemplo_recursao.txt |
| Tempo | 41.0 s |

**Avaliação do revisor:**

> 

---

## 36. `recursao_n3b` (recursao, nível 3)

**Enunciado:**

```
O que acontece na chamada g(3)?

def g(n):
    if n == 0:
        return 1
    return n * g(n - 2)
```

**Alternativas:** A) Devolve 3 · B) Devolve 6 · C) Devolve 0 · D) Estouro de pilha (RecursionError), pois n nunca chega a 0

**Resposta marcada pelo aluno:** A) Devolve 3

**Gabarito:** D) Estouro de pilha (RecursionError), pois n nunca chega a 0

**Explicação verificada (banco de itens):** O caso recursivo vai de 3 para 1 e depois para -1, pulando o caso base n == 0, então as chamadas nunca param.

**Veredito (fixo, gerado por código):** Você marcou: A) Devolve 3. A resposta correta é: D) Estouro de pilha (RecursionError), pois n nunca chega a 0.

| | Modo ancorado |
|---|---|
| **Saída** | A resposta correta é D) Estouro de pilha (RecursionError), pois o caso recursivo de `g(3)` vai para `g(1)`, depois para `g(-1)`, e assim por diante, sem atingir o caso base `n == 0`, resultando em uma chamada infinita de função, que não tem um final. |
| Origem | LLM |
| Fontes | exemplo_recursao.txt |
| Tempo | 38.4 s |

**Avaliação do revisor:**

> 

---
