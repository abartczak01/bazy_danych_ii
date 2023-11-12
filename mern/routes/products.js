const express = require("express");
const recordRoutes = express.Router();
const dbo = require("../db/conn");
const ObjectId = require("mongodb").ObjectId;

recordRoutes.route("/products").get(function(req, res) {
    let db_connect = dbo.getDb("sklep");
    let query = {};

    if (req.query._id) {
        query._id = ObjectId(req.query._id);
    }

    if (req.query.nazwa) {
        query.nazwa = { $regex: req.query.nazwa, $options: "i" };
    }

    if (req.query.cena) {
        query.cena = parseFloat(req.query.cena);
    }

    if (req.query.quantity) {
        query.ilosc = parseInt(req.query.ilosc);
    }

    let sortCriteria = {};
    if (req.query.sortBy) {
        sortCriteria[req.query.sortBy] = req.query.sortOrder === "desc" ? -1 : 1;
    }

    db_connect.collection("products").find(query).sort(sortCriteria).toArray(function(err, result) {
        if (err) throw err;
        res.json(result);
    });
});


recordRoutes.route("/products").post(function(req, res){
    let db_connect = dbo.getDb("sklep");

    db_connect.collection("products").findOne({ nazwa: req.query.nazwa }, function(err, existingProduct) {
        if (err) throw err;

        if (existingProduct) {
            return res.status(400).json({ error: "Nazwa produktu musi być unikalna." });
        } else {
            const newProduct = {
                nazwa: req.query.nazwa,
                cena: req.query.cena,
                opis: req.query.opis,
                ilosc:  req.query.ilosc,
                jednostka_miary: req.query.jednostka_miary
            };

            db_connect.collection("products").insertOne(newProduct, function(err, result) {
                if (err) throw err;
                res.json(result);
            });
        }
    });
});

recordRoutes.route("/products/:id").post(function(req, res) {
    let db_connect = dbo.getDb("sklep");
    let productId = req.params.id;
    let updatedProduct = req.query;

    db_connect.collection("products").findOne({ _id: ObjectId(productId) }, function(err, existingProduct) {
        if (err) throw err;

        if (!existingProduct) {
            return res.status(404).json({ error: "Produkt o podanym ID nie istnieje." });
        } else {
            const validFields = ["nazwa", "cena", "opis", "ilosc", "jednostka_miary"];
            const updateFields = {};

            validFields.forEach(field => {
                if (updatedProduct.hasOwnProperty(field)) {
                    updateFields[field] = updatedProduct[field];
                }
            });

            db_connect.collection("products").updateOne({ _id: ObjectId(productId) }, { $set: updateFields }, function(err, result) {
                if (err) throw err;

                if (result.modifiedCount === 1) {
                    res.json({ message: "Produkt zaktualizowany pomyślnie." });
                } else {
                    res.json({ message: "Nie dokonano żadnych zmian. Sprawdź wprowadzone dane." });
                }
            });
        }
    });
});


recordRoutes.route("/products/:id").delete(function(req, res) {
    let db_connect = dbo.getDb("sklep");
    let myquery = { _id: ObjectId(req.params.id) };

    db_connect.collection("products").findOne(myquery, function(err, existingProduct) {
        if (err) throw err;

        if (!existingProduct) {
            return res.status(404).json({ error: "Produkt o podanym ID nie istnieje." });
        } else {
            db_connect.collection("products").deleteOne(myquery, function(err, result) {
                if (err) throw err;
                res.json({ message: "Produkt usunięty pomyślnie." });
            });
        }
    });
});

recordRoutes.route("/raport").get(function (req, res) {
    let db_connect = dbo.getDb("sklep");
    let query = {};
    // możliwość wyszukiwania produktu po id i nazwie
    if (req.query._id) {
        query._id = ObjectId(req.query._id);
    }

    if (req.query.nazwa) {
        query.nazwa = { $regex: req.query.nazwa, $options: "i" };
    }

    let aggregation = [];

    if ( Object.keys(query).length === 0 ) {
        aggregation = [
            {
                $group: {
                    _id: "$jednostka_miary",
                    łączna_ilość: { $sum: "$ilosc" },
                    łączna_wartość: { $sum: { $multiply: ["$ilosc", "$cena"] } }
                }
            },
            {
                $group: {
                    _id: null,
                    łączna_ilość: { $sum: "$łączna_ilość" },
                    łączna_wartość: { $sum: "$łączna_wartość" },
                    dokładne_dane: { $push: { jednostka_miary: "$_id", ilosc: "$łączna_ilość", wartość: "$łączna_wartość" } }
                }
            },
            { $project: { _id: 0 } }
        ]
    } else {
        aggregation = [
            { $match: query },
            { $project: { _id: 0, nazwa: 1, cena: 1, ilosc: 1, cena: 1, łączna_wartość: { $multiply: ["$ilosc", "$cena"] } } },
        ]
    }

    db_connect.collection("products").aggregate(aggregation).toArray(function (err, result) {
        if (err) throw err;

        res.json(result);
    });
});

module.exports = recordRoutes;