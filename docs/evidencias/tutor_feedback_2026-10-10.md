# Feedback do Tutor: modo ancorado x modo livre (2026-10-10)

Evidência para a revisão pedagógica (Pessoa 4). Gerado por `python -m tia.agentes.tutor.comparar_modos`.

**PROVISÓRIO:** banco de itens e material de apoio são provisórios (A3), até a entrega do conteúdo real.

- Modelo: `qwen3:1.7b` (local, via Ollama). Limite: 200 tokens, até 4 trechos do RAG.
- Em todos os itens, o aluno simulado marcou uma alternativa **errada** (a seguinte à correta).
- **Ancorado** (padrão): o LLM reformula a explicação verificada do item, apoiado nos trechos do material, proibido de calcular ou inventar valores.
- **Livre** (só para comparação): o LLM explica a partir dos trechos do material, sem a explicação verificada.
- **Fallback**: quando não há trecho relevante ou o LLM falha, o aluno recebe a explicação verificada, sem fonte.
- Itens: 36. Ancorado: 36 do LLM, 0 fallback. Livre: 36 do LLM, 0 fallback.

Na **Avaliação do revisor**, indicar por item: a saída de cada modo está correta? Qual modo é melhor? Algum erro conceitual?

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O aluno errou ao escolher a alternativa C) str. O valor 3.14 é do tipo float, pois é um número com parte decimal. A alternativa correta é B) float. | A resposta correta é B) float porque o valor 3.14 é um número com parte decimal, o que é característico do tipo float em Python. |
| Origem | LLM | LLM |
| Fontes | provisorio_variaveis_tipos.txt | provisorio_variaveis_tipos.txt |
| Tempo | 57.8 s | 44.3 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A instrução `idade = 18` cria a variável `idade` com o valor 18, pois o sinal de igual na linguagem Python é utilizado para atribuir o valor da direita ao nome da esquerda. O valor 18 é guardado no nome `idade`. | A instrução idade = 18 cria a variável idade e guarda o valor 18 nela. O sinal = é usado para atribuir valores. |
| Origem | LLM | LLM |
| Fontes | provisorio_variaveis_tipos.txt | provisorio_variaveis_tipos.txt |
| Tempo | 56.8 s | 15.0 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A operação 7 // 2 realiza divisão inteira, descartando a parte decimal. Como 7 dividido por 2 é 3.5, o resultado da divisão inteira é 3. O aluno errou ao escolher B) 3.5. | A divisão inteira // retorna o quociente, não o resto. 7 // 2 é 3. A resposta correta é A) 3 porque 7 // 2 é 3, não 3.5. |
| Origem | LLM | LLM |
| Fontes | provisorio_variaveis_tipos.txt | provisorio_variaveis_tipos.txt |
| Tempo | 60.3 s | 20.9 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A soma de "2" e "3" é realizada com o operador +, que junta textos. Como os valores são strings, o resultado é "23". O aluno errou ao escolher "5". | A soma de strings em Python junta os valores, então "2" + "3" resulta em "23". A função str() converte valores em strings, mas a soma de strings não é matemática. A resposta correta é B) "23" porque a soma de strings é concatenação. |
| Origem | LLM | LLM |
| Fontes | provisorio_variaveis_tipos.txt | provisorio_variaveis_tipos.txt |
| Tempo | 54.6 s | 16.8 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A explicação verificada mostra que a potência é calculada primeiro (4 ** 2 = 16), depois a multiplicação (3 * 16 = 48), e por fim a soma (2 + 48 = 50). O aluno errou ao escolher a alternativa D, pois a ordem das operações matemáticas é importante. | A expressão 2 + 3 * 4 ** 2 segue a precedência das operações: ** (potência) antes de * e /, então * antes de +. Portanto, 4 ** 2 é 16, 3 * 16 é 48, e 2 + 48 é 50. |
| Origem | LLM | LLM |
| Fontes | provisorio_variaveis_tipos.txt | provisorio_variaveis_tipos.txt |
| Tempo | 58.6 s | 20.2 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A explicação verificada mostra que o valor de not (x > 3 and x < 5) or x == 4 é True, pois o conteúdo da expressão interna é False, e o or com qualquer valor verdadeiro mantém o resultado como True. | A expressão not (x > 3 and x < 5) or x == 4 é verdadeira porque x = 5, então x > 3 é True e x < 5 é False. O operador not inverte o valor, então True becomes False. O or verifica se pelo menos um lado é True, e aqui x == 4 é False. |
| Origem | LLM | LLM |
| Fontes | provisorio_variaveis_tipos.txt | provisorio_variaveis_tipos.txt |
| Tempo | 53.5 s | 22.8 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A linha do if termina com dois-pontos, e o bloco é definido pela indentação. O bloco é executado apenas quando a condição é verdadeira (True). | A resposta correta é D) Quando a condição é True, pois o bloco indentado é executado apenas se a condição for verdadeira. |
| Origem | LLM | LLM |
| Fontes | provisorio_condicionais.txt | provisorio_condicionais.txt |
| Tempo | 40.5 s | 34.9 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A linha do if em Python deve terminar com dois-pontos, e o bloco é definido pela indentação. O uso de dois-pontos é essencial para que a estrutura condicional funcione corretamente. | A linha do if em Python termina com dois-pontos (:), pois é a forma padrão para iniciar uma estrutura condicional. |
| Origem | LLM | LLM |
| Fontes | provisorio_condicionais.txt | provisorio_condicionais.txt |
| Tempo | 42.6 s | 10.9 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O código imprime "reprovado", pois a condição `nota >= 5` é falsa, então o bloco do `else` é executado. O código segue a estrutura correta de condicionais em Python, com a ordem adequada para testar as condições. | A estrutura `if-else` verifica se a nota é maior ou igual a 5. Como a nota é 4, a condição `if` é falsa, então o código imprime "reprovado". |
| Origem | LLM | LLM |
| Fontes | provisorio_condicionais.txt | provisorio_condicionais.txt |
| Tempo | 51.2 s | 15.4 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A condição correta é `idade >= 16 and idade < 18`, pois o `and` exige que ambas as comparações sejam verdadeiras. O aluno errou ao usar `not idade < 18`, que é uma operação invertida e não representa a condição desejada. | A resposta correta é C porque a condição teste se idade está entre 16 (inclusive) e 18 (exclusive) com o operador "and". A alternativa D é incorreta porque a expressão "not idade < 18" não define a condição correta. A resposta C é a única que atende à definição da condição. |
| Origem | LLM | LLM |
| Fontes | provisorio_condicionais.txt | provisorio_condicionais.txt |
| Tempo | 45.5 s | 21.5 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O código imprime "bom", pois a primeira condição (`nota >= 7`) é verdadeira, e as demais condições são ignoradas devido à ordem das verificações. | A estrutura condicional if-elif-else testa as condições de cima para baixo. A primeira condição (`nota >= 7`) é verdadeira, então o código imprime "bom". A alternativa A é incorreta porque a primeira condição já é verdadeira, então o código não executa a segunda condição. |
| Origem | LLM | LLM |
| Fontes | provisorio_condicionais.txt | provisorio_condicionais.txt |
| Tempo | 44.6 s | 24.9 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O código imprime "B", pois o valor de x é 10, que é maior que 5, mas menor que 20, portanto o else da condição interna é executado. A estrutura condicional funciona de forma sequencial, e a ordem das condições é importante, pois o código apenas executa o primeiro bloco verdadeiro. | A estrutura `if-elif` testa as condições de cima para baixo. A primeira condição (`x > 5`) é verdadeira, então o código imprime "A". A resposta correta é A) B porque a primeira condição é verdadeira, e o código imprime "A". |
| Origem | LLM | LLM |
| Fontes | provisorio_condicionais.txt | provisorio_condicionais.txt |
| Tempo | 52.6 s | 17.9 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno está correta, pois range(4) começa em 0 e não inclui o 4, produzindo os números 0, 1 e 2. A explicação verificada confirma isso. | A função range(4) gera números de 0 a 3, pois o último valor não é incluído. O laço não executa para o valor 4. A resposta correta é C) 0, 1, 2, 3. |
| Origem | LLM | LLM |
| Fontes | provisorio_repeticao.txt | provisorio_repeticao.txt |
| Tempo | 9.7 s | 18.3 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno errou porque a condição do while precisa ser atualizada para que o laço pare. A alternativa correta é D) Quando a condição se torna falsa. | A resposta correta é D) Quando a condição se torna falsa, pois o laço termina quando a condição é falsa. O erro do aluno foi esquecer de que o laço termina quando a condição se torna falsa. O while repete enquanto a condição for verdadeira, e quando ela se torna falsa, o laço para. |
| Origem | LLM | LLM |
| Fontes | provisorio_repeticao.txt | provisorio_repeticao.txt |
| Tempo | 47.4 s | 22.6 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O código imprime 10, pois o loop percorre os números de 1 a 4 e soma-os. A explicação verificada confirma que a soma é 1 + 2 + 3 + 4 = 10. | A resposta correta é A) 10 porque o loop percorre os números de 1 a 4, somando-os. O aluno ERROU ao escolher B) 15, pois a soma é 1 + 2 + 3 + 4 = 10. O loop termina quando o range é 5, que não inclui o 5. |
| Origem | LLM | LLM |
| Fontes | provisorio_repeticao.txt | provisorio_repeticao.txt |
| Tempo | 11.3 s | 22.5 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A instrução `break` interrompe o laço imediatamente, impedindo que o código dentro do laço continue sendo executado. Ela é útil para sair do laço precocemente, como em casos de condições específicas ou quando se deseja encerrar o loop de forma controlada. | O comando break interrompe o laço imediatamente. O comando break é usado para sair do laço rapidamente. Ele é útil quando se deseja interromper o loop de forma abrupta. |
| Origem | LLM | LLM |
| Fontes | provisorio_repeticao.txt | provisorio_repeticao.txt |
| Tempo | 52.3 s | 16.3 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O código imprime 4, pois o acumulador é zerado a cada iteração do laço e apenas guarda o último valor de `i`, que é 4. | A resposta correta é C) 4 porque o loop executa o bloco apenas uma vez, com i = 4, e o total é somado com 4. O erro foi devido ao aluno escolher D) 5, adivinhando o resultado incorretamente. |
| Origem | LLM | LLM |
| Fontes | provisorio_repeticao.txt | provisorio_repeticao.txt |
| Tempo | 6.6 s | 18.1 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O código imprime 12, pois o contador é atualizado em cada iteração do laço enquanto a condição é verdadeira. A variável `i` começa em 0 e é incrementada por 3 em cada passo, resultando em 3, 6, 9, 12, e o laço termina quando `i` é 12. | A resposta correta é B) 12 porque o contador `i` é atualizado dentro do laço, fazendo com que ele vá de 0, 3, 6, 9, e ao sair do laço, o valor de `i` é 9. No print, é mostrado o valor após a execução do laço, que é 9. Porém, a resposta correta é B) 12, pois o código imprime o valor final do contador, que é 9, não 12. |
| Origem | LLM | LLM |
| Fontes | provisorio_repeticao.txt | provisorio_repeticao.txt |
| Tempo | 57.9 s | 30.9 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A palavra-chave que define uma função em Python é "def". A função é definida com essa palavra-chave, seguida pelo nome da função e pelos parâmetros que ela recebe. O trecho do material confirma que a função é definida com "def". | A palavra-chave "def" é utilizada para definir uma função em Python. |
| Origem | LLM | LLM |
| Fontes | provisorio_funcoes.txt | provisorio_funcoes.txt |
| Tempo | 44.9 s | 30.5 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A função `dobro(x)` é definida, mas não é executada até que seja chamada, como `dobro(5)`. O retorno da função é o resultado da multiplicação por 2, que é armazenado e pode ser utilizado em outras partes do código. | A função é definida, mas só é executada quando chamada. O return retorna o dobro de x, mas não imprime nada. |
| Origem | LLM | LLM |
| Fontes | provisorio_funcoes.txt | provisorio_funcoes.txt |
| Tempo | 44.9 s | 14.0 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A diferença entre print e return é que o print mostra texto na tela, enquanto o return entrega um valor para quem chamou a função. O return encerra a função e devolve um valor, enquanto o print apenas mostra texto. | A diferença entre print e return é que o return devolve um valor para quem chamou a função, enquanto o print apenas mostra texto na tela. |
| Origem | LLM | LLM |
| Fontes | provisorio_funcoes.txt | provisorio_funcoes.txt |
| Tempo | 42.7 s | 11.8 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A função `f` não retorna nenhum valor, portanto, o valor de `r` será `None`. O retorno de uma função sem `return` é `None`. A função não calcula o valor de `r`, pois não possui `return`. | A função não retorna nenhum valor, portanto o valor de r é None. A função recebe um parâmetro, mas não o altera. O código é válido, mas a resposta correta é A) None. |
| Origem | LLM | LLM |
| Fontes | provisorio_funcoes.txt | provisorio_funcoes.txt |
| Tempo | 45.0 s | 13.2 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A variável `resultado` é local à função `soma` e não existe fora dela. Portanto, ao executar `print(resultado)`, ocorrerá um erro, pois a variável não foi declarada. O erro é um `NameError`, pois `resultado` só é acessível dentro da função e não é visível em outras partes do código. | A função não retorna o valor de `resultado`, pois o `return` é omitido. O `print` acessa `resultado` que não existe fora da função. |
| Origem | LLM | LLM |
| Fontes | provisorio_funcoes.txt | provisorio_funcoes.txt |
| Tempo | 49.2 s | 13.8 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A chamada teste(3) executa a condição if n > 0, que é verdadeiro, e retorna "positivo" sem imprimir nada, pois o return encerra a função imediatamente. O aluno errou ao escolher a alternativa C, pois a resposta correta é B. | A função teste(n) retorna "positivo" quando n > 0, pois o if é verdadeiro. O return não é executado após o print, portanto não imprime "depois". A resposta correta é B. |
| Origem | LLM | LLM |
| Fontes | provisorio_funcoes.txt | provisorio_funcoes.txt |
| Tempo | 46.7 s | 18.5 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno foi correta, pois notas[0] é o primeiro elemento da lista, que vale 7. A explicação verificada confirma que os índices começam em 0, portanto notas[0] é 7. | A resposta correta é A) 7, pois notas[0] refere-se ao primeiro elemento da lista. |
| Origem | LLM | LLM |
| Fontes | provisorio_listas_strings.txt | provisorio_listas_strings.txt |
| Tempo | 49.7 s | 39.9 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno está correta, pois o valor de len("Python") é 6. A função len retorna o número de caracteres da string, e "Python" possui 6 letras. | A função len contabiliza o número de caracteres em uma string. A string "Python" possui 6 caracteres. |
| Origem | LLM | LLM |
| Fontes | provisorio_listas_strings.txt | provisorio_listas_strings.txt |
| Tempo | 46.2 s | 10.6 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno foi incorreta, pois o índice negativo em listas em Python contam do fim. O valor de notas[-1] é 9, que é o último elemento da lista. | A resposta correta é C) 9 porque o índice -1 referência o último elemento da lista. |
| Origem | LLM | LLM |
| Fontes | provisorio_listas_strings.txt | provisorio_listas_strings.txt |
| Tempo | 46.7 s | 10.7 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno foi correta em sua compreensão da lógica do fatiamento, mas errou o resultado final. O fatiamento [1:4] pegava o índice 1 até o 3 (o último índice não é incluído), resultando em "yth". A explicação verificada confirma que o correto é "yth". | A resposta correta é B) "yth" porque o fatiamento "Python"[1:4] seleciona os caracteres da posição 1 até antes da posição 4, ou seja, "y", "t", "h". O erro ocorre porque o aluno escolheu C) "ytho", que inclui o caractere "o" que não está na posição 4. |
| Origem | LLM | LLM |
| Fontes | provisorio_listas_strings.txt | provisorio_listas_strings.txt |
| Tempo | 57.4 s | 19.4 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno é incorreta, pois strings em Python são imutáveis. O código não muda o valor de `s` porque strings não podem ser alteradas diretamente. O aluno errou ao acreditar que o código alteraria o conteúdo da string. | A resposta correta é A) Erro, pois strings são imutáveis, pois o código tenta modificar uma string não mutável. |
| Origem | LLM | LLM |
| Fontes | provisorio_listas_strings.txt | provisorio_listas_strings.txt |
| Tempo | 52.6 s | 13.7 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O código quebra a string "eu gosto de python" em uma lista de 4 palavras e adiciona "!" à lista, resultando em uma lista com 5 elementos. Portanto, o resultado é 5. | A função `split()` quebra a string em uma lista de palavras, resultando em ["eu", "gosto", "de", "python"]. O método `append()` adiciona o elemento "!" à lista. A função `len()` retorna o tamanho da lista, que é 5. |
| Origem | LLM | LLM |
| Fontes | provisorio_listas_strings.txt | provisorio_listas_strings.txt |
| Tempo | 49.8 s | 17.8 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A função recursiva é uma técnica de programação em que uma função chama a si mesma para resolver um problema dividido em subproblemas menores. Ela precisa de um caso base para parar de chamar a si mesma, evitando loops infinitos. O aluno errou ao associar a função recursiva com vários parâmetros, pois a chave é a chamada à si mesma, não o número de parâmetros. | A função recursiva chama a si mesma para resolver problemas menores. O caso base é necessário para evitar loops infinitos. A resposta correta é C, pois a função recursiva é caracterizada por chamar a si mesma. |
| Origem | LLM | LLM |
| Fontes | exemplo_recursao.txt | exemplo_recursao.txt |
| Tempo | 37.7 s | 28.1 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O caso base é a condição que faz a função parar de chamar a si mesma. Sem ele, a função entra em um loop infinito de chamadas, causando erros de estouro de pilha. O caso base é essencial para garantir que a recursão acabe. | O caso base é a condição que faz a função parar de chamar a si mesma, evitando um loop infinito. O caso base é essencial para garantir que a recursão acabe. Sem um caso base claro, a função entra em um loop infinito. |
| Origem | LLM | LLM |
| Fontes | exemplo_recursao.txt | exemplo_recursao.txt |
| Tempo | 28.1 s | 16.3 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A função recursiva sem caso base entra em um loop infinito de chamadas, esgotando a memória e causando o erro de estouro de pilha. O caso base é essencial para parar a recursão e evitar o loop infinito. | A função entra em um loop infinito de chamadas, pois não há um caso base definido. Sem caso base, a recursão continua indefinidamente, causando estouro de pilha. |
| Origem | LLM | LLM |
| Fontes | exemplo_recursao.txt | exemplo_recursao.txt |
| Tempo | 25.8 s | 13.7 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | O caso base no cálculo recursivo do fatorial é **fatorial(0) = 1**, pois é a condição que faz a função parar de chamar a si mesma. O caso recursivo é **fatorial(n) = n * fatorial(n - 1)**, que reduz o problema a uma versão menor. | A resposta correta é A) fatorial(0) = 1, pois é o caso base que faz a função parar de chamar a si mesma. O caso base é a condição que interrompe o processo de recursão. |
| Origem | LLM | LLM |
| Fontes | exemplo_recursao.txt | exemplo_recursao.txt |
| Tempo | 30.2 s | 14.6 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A resposta do aluno está correta, pois o valor de f(4) é 10, como calculado pela recursão. A função soma os valores de 4 + 3 + 2 + 1 + 0, resultando em 10. | A função f(n) é uma recursão que soma os números de 0 a n. O caso base é f(0) = 0. A resposta correta é C) 10 porque a função calcula a soma de 0 + 1 + 2 + 3 + 4 = 10. |
| Origem | LLM | LLM |
| Fontes | exemplo_recursao.txt | exemplo_recursao.txt |
| Tempo | 28.2 s | 17.1 s |

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

| | Modo ancorado | Modo livre |
|---|---|---|
| **Saída** | A chamada `g(3)` resulta em um estouro de pilha, pois o programa nunca alcança o caso base `n == 0` e as chamadas recursivas se tornam infinitas. | A função g(n) chama a si mesma indefinidamente, pois n nunca chega a 0. A recursão não tem um caso base bem definido. O programa entra em um loop infinito de chamadas, causando estouro de pilha. |
| Origem | LLM | LLM |
| Fontes | exemplo_recursao.txt | exemplo_recursao.txt |
| Tempo | 25.7 s | 17.6 s |

**Avaliação do revisor:**

> 

---
