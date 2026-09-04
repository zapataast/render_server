# Flask MongoDB + Cloudinary Profile

Registration:
- phone
- nickname
- password

After login, `/profile` allows:
- profile image
- nickname
- email
- birthdate
- bio

Image is stored on Cloudinary. MongoDB stores only the image URL/public id.

## .env

```env
SECRET_KEY=my-secret
MONGO_URI=mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/render_server?retryWrites=true&w=majority
CLOUDINARY_URL=cloudinary://API_KEY:API_SECRET@CLOUD_NAME
```

## Local

```bat
cd C:\Users\myagmardorj\Documents\render_server
python -m pip install -r requirements.txt
python app.py
```

## Render Environment

Add:
- MONGO_URI
- CLOUDINARY_URL
- SECRET_KEY

## Push

```bat
cd C:\Users\myagmardorj\Documents\render_server
git add .
git commit -m "Add editable profile and Cloudinary image upload"
git push origin main
```
