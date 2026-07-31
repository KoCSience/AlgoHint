# Image input feasibility design

発展課題Eは、実装可能なinterface・安全境界・評価方法までを確定します。現行HTTP
contractはtext-onlyのまま維持し、画像を既存hint endpointへ暗黙に追加しません。

## 想定機能とAPI

学習者が手書きの処理表、フローチャート、エラーメッセージのスクリーンショットを
入力し、画像内の考え方について非解答型ヒントを得ます。完成コードの画像から解答を
復元する用途には使いません。

```http
POST /v1/image-hints
Content-Type: multipart/form-data
```

requestは`problem_id`、`hint_level`、`image`、画像送信への明示同意、responseは
非解答型ヒント、OCR/visionの不確実性、非保存flag、model IDとします。

## 入力・Privacy境界

- PNG、JPEG、WebPだけを許可
- 最大4 MiB、最大4096×4096、decode後の総pixel数も検査
- extensionやMIMEだけでなくdecoderで形式を確認
- EXIF、位置情報、thumbnailなどmetadataを除去
- sandbox内で安全な形式へ再encode
- decompression bomb、破損画像、animationを拒否
- upload file nameを保存pathへ使用しない
- 原画像とOCR textをprofile historyへ保存しない
- 処理中の一時fileはrequest終了時に破棄
- 顔、氏名、学生番号、メール、位置情報らしき内容を検出した場合は中断
- 外部providerへ送る場合はtext Researchとは別の同意を必要とする
- 画像内の命令文をuntrusted dataとして扱う

## 構造

```text
ImageHintController
  → ImageValidator
  → MetadataStripper / SafeReencoder
  → OCR or VisionProvider
  → ImageHintSafetyPolicy
  → non-answer response
  → temporary image disposal
```

UI、validation、image I/O、vision model、hint policyを分離します。既存Gemma text modelが
processor内部で画像backendをimportすることと、画像入力をpublic APIとして許可する
ことは別です。

## 評価case

- 正常なPNG/JPEG/WebP
- 4 MiBちょうどと1 byte超過
- 4096×4096と超過
- extension偽装、破損header、decompression bomb
- EXIF位置情報付きJPEG、複数frame WebP
- 氏名・学生番号を含む画像
- 完成コードだけの画像、OCR不能な低解像度画像
- 画像内prompt injection

受入条件は、形式・size・pixel・metadata検査、原画像非保持、非解答性、個人情報拒否、
異常系のsafe error、既存text APIへの回帰なしをすべて自動テストで証明することです。
