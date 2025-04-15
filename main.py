import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputFile
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler, filters,
                          ConversationHandler, CallbackQueryHandler, ContextTypes)
import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import io
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from pdf2image import convert_from_bytes

# Estados del formulario
(FECHA, CLIENTE_INFO, PRODUCTO, CANTIDAD_PAGADA, FOTOS, CONFIRMACION) = range(6)

# Datos temporales
user_data = {}

# Configura el logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bienvenido al generador de tickets de Zaik Store 🧾\nPor favor, ingresa la *fecha de compra* (ej. 14 de Abril de 2025):", parse_mode='Markdown')
    return FECHA

async def recibir_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data[update.effective_chat.id] = {
        "fecha": update.message.text,
        "productos": [],
        "fotos": []
    }
    await update.message.reply_text("Ahora ingresa los datos del cliente en este formato (cada uno en una línea):\n\nNombre\nCorreo\nNúmero\nDirección\nColonia\nCiudad\nEstado\nPaís")
    return CLIENTE_INFO

async def recibir_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.split('\n')
    if len(lines) < 8:
        await update.message.reply_text("Por favor, asegúrate de escribir los 8 datos requeridos (uno por línea). Intenta de nuevo.")
        return CLIENTE_INFO

    user_data[update.effective_chat.id].update({
        "cliente": {
            "nombre": lines[0], "correo": lines[1], "numero": lines[2],
            "direccion": lines[3], "colonia": lines[4],
            "ciudad": lines[5], "estado": lines[6], "pais": lines[7]
        }
    })
    await update.message.reply_text("Perfecto ✅\nAhora ingresa el producto en este formato (cada dato separado por coma):\n\nDescripción, Talla, Cantidad, Costo, Descuento")
    return PRODUCTO

async def recibir_producto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    parts = update.message.text.split(',')
    if len(parts) < 5:
        await update.message.reply_text("Formato incorrecto. Por favor usa: Descripción, Talla, Cantidad, Costo, Descuento")
        return PRODUCTO

    descripcion, talla, cantidad, costo, descuento = [p.strip() for p in parts]
    total = (float(costo) - float(descuento)) * float(cantidad)
    user_data[chat_id]['productos'].append({
        "descripcion": descripcion,
        "talla": talla,
        "cantidad": float(cantidad),
        "costo": float(costo),
        "descuento": float(descuento),
        "total": total
    })

    keyboard = [
        [InlineKeyboardButton("➕ Agregar otro producto", callback_data='agregar')],
        [InlineKeyboardButton("✅ Finalizar productos", callback_data='finalizar')]
    ]
    await update.message.reply_text("¿Qué quieres hacer ahora?", reply_markup=InlineKeyboardMarkup(keyboard))
    return PRODUCTO

async def manejar_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'agregar':
        await query.edit_message_text("Ingresa el siguiente producto (Descripción, Talla, Cantidad, Costo, Descuento):")
        return PRODUCTO
    else:
        await query.edit_message_text("¿Cuánto fue la *cantidad pagada* por el cliente?", parse_mode='Markdown')
        return CANTIDAD_PAGADA

async def recibir_pago(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_data[chat_id]['cantidad_pagada'] = float(update.message.text)
    await update.message.reply_text("Ahora por favor *envíame las fotos* del pedido. Puedes mandar varias.", parse_mode='Markdown')
    return FOTOS

async def recibir_fotos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if 'photo' in update.message.to_dict():
        photo = update.message.photo[-1].file_id
        user_data[chat_id]['fotos'].append(photo)
        await update.message.reply_text("Foto recibida 📸 Puedes enviar más o escribe /listo cuando hayas terminado.")
    return FOTOS

async def fotos_finalizadas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    data = user_data[chat_id]

    # Crear PDF
    nombre = data['cliente']['nombre'].replace(" ", "")
    fecha = data['fecha'].replace(" ", "")
    filename = f"ticket_{nombre}_{fecha}.pdf"
    pdf_path = f"/tmp/{filename}"

    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, "Zaik Store - Ticket de compra")
    y -= 30
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Fecha: {data['fecha']}")
    y -= 20

    cli = data['cliente']
    c.drawString(50, y, f"Cliente: {cli['nombre']}")
    y -= 15
    c.drawString(50, y, f"Correo: {cli['correo']} | Número: {cli['numero']}")
    y -= 15
    c.drawString(50, y, f"Dirección: {cli['direccion']}, {cli['colonia']}, {cli['ciudad']}, {cli['estado']}, {cli['pais']}")
    y -= 30

    subtotal = 0
    for prod in data['productos']:
        c.drawString(50, y, f"{prod['descripcion']} | Talla: {prod['talla']} | Cantidad: {prod['cantidad']} | Costo: ${prod['costo']} | Desc: ${prod['descuento']} | Total: ${prod['total']:.2f}")
        y -= 15
        subtotal += prod['total']

    descuento_total = sum(p['descuento'] * p['cantidad'] for p in data['productos'])
    total = subtotal
    pagado = data['cantidad_pagada']
    restante = total - pagado

    y -= 20
    c.drawString(50, y, f"Subtotal: ${subtotal:.2f}")
    y -= 15
    c.drawString(50, y, f"Descuento total: ${descuento_total:.2f}")
    y -= 15
    c.drawString(50, y, f"Total: ${total:.2f}")
    y -= 15
    c.drawString(50, y, f"Pagado: ${pagado:.2f}")
    y -= 15
    c.drawString(50, y, f"Saldo restante: ${restante:.2f}")
    y -= 30

    # Fotos (4 por fila)
    col = 0
    img_y = y
    for i, file_id in enumerate(data['fotos']):
        file = await context.bot.get_file(file_id)
        f = await file.download_as_bytearray()
        image = Image.open(io.BytesIO(f)).convert('RGB')
        image.thumbnail((120, 120))
        img_io = io.BytesIO()
        image.save(img_io, format='PNG')
        img_io.seek(0)
        c.drawImage(ImageReader(img_io), 50 + col * 130, img_y, width=120, height=120)
        col += 1
        if col == 4:
            col = 0
            img_y -= 130

    c.save()

    # Convertir PDF a imagen para preview
    with open(pdf_path, 'rb') as f:
        images = convert_from_bytes(f.read())
    img_io = io.BytesIO()
    images[0].save(img_io, format='PNG')
    img_io.seek(0)

    await update.message.reply_photo(photo=img_io, caption="🧾 Aquí está tu ticket generado.")

    # Enviar PDF
    with open(pdf_path, 'rb') as pdf_file:
        await update.message.reply_document(document=InputFile(pdf_file, filename=filename), caption="📥 Descarga tu ticket en PDF")

    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelado 🛑 Puedes empezar de nuevo con /start")
    return ConversationHandler.END

if __name__ == '__main__':
    app = ApplicationBuilder().token("7561928347:AAFA1Q48N8InTOzXPLmfQ6a-cibWNw9LdJ0").build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_fecha)],
            CLIENTE_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_cliente)],
            PRODUCTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_producto),
                CallbackQueryHandler(manejar_botones)
            ],
            CANTIDAD_PAGADA: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_pago)],
            FOTOS: [
                MessageHandler(filters.PHOTO, recibir_fotos),
                CommandHandler('listo', fotos_finalizadas)
            ],
        },
        fallbacks=[CommandHandler('cancelar', cancelar)]
    )

    app.add_handler(conv_handler)
    app.run_polling()
